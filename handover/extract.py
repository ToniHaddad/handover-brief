"""Deterministic extraction of handover items from a chat thread.

One pass over the messages in posting order keeps the state a careful reader
keeps in their head: the current deadlines, the open proposals, the pending
requests. Each message is first described by cue patterns (`describe`), then
applied to that state (`Extractor.apply`). A second pass looks for questions
nobody answered. Every item records the ids of the messages it came from.

No model, no network: the same thread always gives the same brief.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timedelta

from .dates import DateMention, find_dates
from .model import Item, Message, Thread, Version

# ---------------------------------------------------------------- cue patterns

AGREE_START = re.compile(
    r"^(?:yes|yep|yeah|yup|ok|okay|agreed|agree|sure|fine|sounds good|works for me|fine by me|"
    r"go ahead|go for it|approved|deal|good idea|great idea|makes sense|that works|perfect|"
    r"no objection|vale|dale|listo|de acuerdo|perfecto|claro|correct|absolutely|definitely|\+1|"
    r"d'accord|parfait|ça marche|ca marche|entendu|ok pour moi|tamam|"
    r"تمام|موافق|موافقة|ماشي|اوكي|أوكي|اتفقنا|اكيد|أكيد|طيب)(?!\w)", re.I)
AGREE_ANY = re.compile(
    r"\b(?:agreed|i agree|fine by me|works for me|sounds good|go ahead|makes sense|good idea|"
    r"happy with that|let's do (?:it|that)|approved|go for it|no objection|that works|d'accord|ça marche)\b"
    r"|\bworks[.!]*$|(?<!\w)(?:موافق|اتفقنا)(?!\w)", re.I)
AGREE_NOT = re.compile(r"\b(?:as agreed|not agreed|never agreed|if agreed|pas d'accord)\b", re.I)
DISAGREE = re.compile(
    r"^(?:no|nope|not really|i'd rather not|i would rather not|i don't think|i disagree|can't|cannot|"
    r"not possible|let's not|non|pas possible|لا)(?!\w)"
    r"|\b(?:too late|won't approve|not approve|rather not|disagree|pas d'accord)\b|مش ممكن|ما بيمشي", re.I)
PROPOSE = re.compile(
    r"\b(?:let's|let us|i propose|i suggest|i'd suggest|we could|why don't we|how about|"
    r"what about \w+ing|what if we|should we|shall we|could we|can we|i'd like|i would like|"
    r"my suggestion|proposal:|suggested|proposes|proposed|i think we should|maybe we (?:should|could)|"
    r"perhaps we|suggest we|propose we|change of plan|on pourrait|je propose|et si on)\b"
    r"|(?<!\w)(?:شو رأيكم|شو رأيك|بقترح|منقترح)(?!\w)", re.I)
PROPOSE_NOT = re.compile(r"\b(?:let's see|we'll see|let's not)\b", re.I)
INFO_QUESTION_START = re.compile(
    r"^(?:who|what|when|where|why|which|how|has|have|is|are|was|were|did|do|does|will|would|any|"
    r"anyone|anybody|est-ce|qui|quand|où|comment|pourquoi|quel|quelle|"
    r"مين|شو|وين|ايمتى|إيمتى|كيف|ليش|هل|في حدا|حدا)(?!\w)", re.I)
REQUEST = re.compile(r"\b(?:can you|could you|would you|can your team|could your team|please|pls|"
                     r"can the \w+|could the \w+|peux-tu|pouvez-vous|tu peux|merci de)\b"
                     r"|(?<!\w)(?:فيك|فيكي|بليز)(?!\w)", re.I)
# "I'll <verb>" is a claim unless the verb says nothing about taking a task.
NOT_TASK = (r"be|have|try|see|wait|think|probably|need|let|keep|tell|come|go|leave|believe|look|join|"
            r"stay|miss|only|just|still|never|also be|update you|get back|let you know|hope|guess|"
            r"assume|say|mention|remember|forget|lose|die|sleep|survive")
CLAIM = re.compile(
    rf"\b(?:i'll|i will|i can|i'm going to|let me)\s+(?:also\s+|now\s+|then\s+)?(?!(?:{NOT_TASK})\b)[a-z]+"
    r"|\bleave it with me\b|\bi'm on it\b|^on it\b|\bi'll take (?:it|this|that)\b"
    r"|\bi(?:'ve)? got (?:it|this)\b|\b(?:yo )?me encargo\b|\blo hago yo\b"
    r"|\bje m'en (?:occupe|charge)\b|\bje vais (?!être|voir|attendre)\w+"
    r"|(?<!\w)(?:عليّ|خليها عليّ|خليها علي|بتكفل|انا بعمل|أنا بعمل|انا ببعت|أنا ببعت|انا بجيب|أنا بجيب)(?!\w)", re.I)
ACCEPT_START = re.compile(
    r"^(?:yes|yep|yeah|ok|okay|sure|on it|will do|no problem|done|consider it done|leave it with me|"
    r"fine|of course|vale|dale|claro|listo|i'll|i will|i can|oui|d'accord|entendu|"
    r"تمام|اكيد|أكيد|ماشي|حاضر|ايه|إيه)(?!\w)", re.I)
TAKEOVER = re.compile(r"\b(?:take(?:s)? (?:it )?over|taking over|hand(?:ing)? (?:it )?over|instead of \w+ doing)\b", re.I)
MOVE = re.compile(
    r"\b(?:push(?:ed|es|ing)?|mov(?:e|ed|es|ing)|postpon(?:e|ed|es|ing)|reschedul(?:e|ed|ing)|"
    r"slip(?:ped|s)?|delay(?:ed|s)?|bring(?:ing)? forward|brought forward|"
    r"extend(?:ed|s|ing)?|bump(?:ed|s)?|chang(?:e|ed|es))\b[^.?!]{0,40}?\b(?:to|until|till)\b"
    r"|\bnow\s+(?:on\s+|due\s+|is\s+)?(?:the\s+)?(?=monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|\d)"
    r"|\bnew (?:\w+ )?(?:deadline|date|day)\b|\binstead of\b|\bextension (?:to|until|till)\b"
    r"|\b(?:have|has|got) until\b"
    r"|\b(?:report|repouss|décal|decal|avanc)[ée]e?s?\s+(?:à|a|au)\b"
    r"|(?<!\w)(?:تأجل|تأجّل|تأجلت|تأجّلت|أجّلنا|أجلنا|اجلنا|تأجيل)(?!\w)", re.I)
CORRECTION = re.compile(
    r"\b(?:sorry,? i meant|i meant|correction|typo|should have said|should read|my mistake|my bad|oops|"
    r"je voulais dire)\b"
    r"|^\*|(?<!\w)(?:قصدي|عفوا قصدي)(?!\w)"
    r"|\b\d{1,2}(?:st|nd|rd|th)? not (?:the )?\d{1,2}(?:st|nd|rd|th)?\b", re.I)
CANCEL = re.compile(
    r"\b(?:cancel(?:led|ed|ling|s)?|called off|call(?:ing)? off|is off|are off|'s off|"
    r"no longer (?:need(?:ed)?|happening|required|going ahead)|not needed|"
    r"don't need [^.]{0,40}after all|dropping (?:that|this|the|it)|drop (?:that|this|the|it)|"
    r"scrap(?:ped|ping)? (?:that|this|the|it)|not going ahead|won't go ahead|no point in|"
    r"not happening|won't happen|forget (?:about )?(?:the|that|it)|annul(?:é|ée|és|ées|e|er)|n'a plus lieu)\b"
    r"|\bno need (?:for|to) [^.]{0,40}(?:anymore|any more)\b"
    r"|(?<!\w)(?:ملغى|ملغية|ملغاة|انلغى|انلغت|ألغي|الغي|الغاء|إلغاء|ألغينا|الغينا|كنسلنا|تكنسل|تكنسلت)(?!\w)", re.I)
# "the admin is off" is a person away, not a task called off
OFF_PERSON = re.compile(r"\b(?:he|she|they|i|admin|driver|manager|keeper|everyone|nobody)\s+(?:is|are|'s|'m)\s+off\b", re.I)
DECISION = re.compile(
    r"\bdecision(?: from [^:.]{1,40})?:|\bfinal answer\b[^:.]{0,40}:|\bdécision\b[^:.]{0,40}:|"
    r"\b(?:we(?:'ve| have)? decided|it's decided|it is decided|final decision|has decided|"
    r"the decision is|decided to)\b|(?<!\w)(?:القرار|تقرر)(?!\w)", re.I)
REVERSAL = re.compile(
    r"\b(?:switch(?:ing)?|instead|change of plan|revised|revise|scrap|reverse|reversing|no longer|"
    r"rather than|from this round|replace|replacing|overrule|back to|actually|on second thought|"
    r"changed our minds?|change of mind|finalement|plutôt)\b|(?<!\w)(?:بدل|بالآخر)(?!\w)", re.I)
NOT_A_DEADLINE = re.compile(
    r"\b(?:let's see|we'll see|i'm (?:off|away|on leave|travelling|starting)|we start|"
    r"i start|starting the|we're starting|i can only (?:come|make|do)|i'm only free|only free on)\b", re.I)
# A same-day word ("today", "tonight") sets a deadline only next to a word that asks for something.
TODAY_WORDS = re.compile(r"^(?:today|tonight|this\s+\w+|end\s+of|eod|cob|aujourd|ce\s+|اليوم|الليلة)", re.I)
DUE_CUE = re.compile(
    r"\b(?:by|before|until|due|deadline|must|need to|needs to|has to|have to|dispatch|send|deliver|"
    r"submit|finish|load|close|closes|lock|locks|confirm|avant|pour)\b", re.I)
CHATTER = re.compile(
    r"\b(?:coffee|lunch|mug|match|football|weather|rain|snow|dust storm|batteries|birthday|"
    r"fever|sick|get well|pole sana|traffic|kitchen|cake|tea|dinner|breakfast|holiday plans|"
    r"almuerzo|cafe|café|lluvia|manouche|zaatar|bakery)\b|(?<!\w)(?:قهوة|ترويقة|منقوشة)(?!\w)", re.I)
STILL = re.compile(r"\bstill\b", re.I)
ANSWER_START = re.compile(
    r"^(?:yes|no|yeah|nope|not yet|it's|it is|they|we|the|i think|already|done|sent|i|he|she|"
    r"none|all|only|sí|si|oui|non|نعم|لا|ايه|إيه|ما في)(?!\w)", re.I)
MENTION = re.compile(r"@(\w+)")
ANAPHORA = re.compile(r"\b(?:it|them|that|this|one)\b", re.I)
CODE = re.compile(r"\b[a-z]{1,5}-\d{2,4}(?:-\d{1,6})?\b", re.I)

STOP = set("""
a an the and or but if so of to in on at by for from with without about into over after before
is are was were be been being am do does did have has had will would can could should shall may
might must need needs needed i you he she it we they me him her us them my your our their its this
that these those there here what which who whom whose when where why how all any some no not yes
ok okay just also still now then than too very really more less much many one two three get got
let lets let's please thanks thank sorry hi hello morning all team guys fyi re as up out off back
monday tuesday wednesday thursday friday saturday sunday today tomorrow tonight week weeks day days
month months january february march april may june july august september october november december
end new next last this first deadline date time noon am pm i'll i'm we're it's that's don't can't
won't isn't we'll they're there's what's here's she'll he'll you'll said says say told tell
good great sure fine agreed agree moved pushed push cancelled cancel instead meant
les des une est pour pas que qui dans sur avec par plus été
""".split())


def keywords(text: str) -> set[str]:
    out = {c.lower() for c in CODE.findall(text)}  # WH-07, S-03, FA-2026 name things precisely
    rest = CODE.sub(" ", text.lower()).replace("-", " ")
    for raw in re.findall(r"[a-záàâçéèêëîïôûùüñ0-9'؀-ۿ]+", rest):
        w = raw.strip("'")
        if w.endswith("'s"):
            w = w[:-2]
        if w in STOP or len(w) < 3 or w.isdigit():
            continue
        for suffix in ("ing", "ed", "es", "s"):
            if len(w) > 4 and w.isascii() and w.endswith(suffix) and not w.endswith("ss"):
                w = w[: -len(suffix)]
                break
        if w not in STOP:
            out.add(w)
    return out


def sentences(text: str) -> list[tuple[int, str]]:
    """Split into sentences, keeping each one's start offset."""
    out, start = [], 0
    for m in re.finditer(r"[.!?\u061f]+(?:\s+|$)|\n+", text):
        chunk = text[start:m.end()].strip()
        if chunk:
            out.append((start, chunk))
        start = m.end()
    if text[start:].strip():
        out.append((start, text[start:].strip()))
    return out


def is_due(mention: DateMention, sentence: str) -> bool:
    """"Tonight" or "today" alone is usually a report ("a school opened tonight"), not a deadline."""
    if TODAY_WORDS.match(mention.text.strip()):
        return bool(DUE_CUE.search(sentence))
    return True


def short(text: str, limit: int = 140) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# ---------------------------------------------------------------- message features


@dataclass
class Features:
    dates: list[DateMention]
    sents: list[tuple[int, str]]
    question: str | None = None  # the question sentence, if any
    info_question: bool = False
    proposal: str | None = None
    date_proposal: bool = False
    request: str | None = None
    request_to: str | None = None
    agree: bool = False
    disagree: bool = False
    claim: str | None = None
    claim_dates: list[DateMention] = field(default_factory=list)
    cancel_clause: str = ""
    accept: bool = False
    takeover: bool = False
    move: re.Match | None = None
    correction: bool = False
    cancel: str | None = None
    decision: bool = False
    reversal: bool = False
    chatter: bool = False
    no_deadline: bool = False
    mentions: list[str] = field(default_factory=list)


def describe(msg: Message, people: dict[str, str]) -> Features:
    """Describe one message with the cue patterns. `people` maps first names to full names."""
    text = msg.text.strip()
    body = MENTION.sub(lambda m: m.group(1), text)
    f = Features(dates=[d for d in find_dates(body, msg.day) if d.kind != "past"], sents=sentences(body))
    f.mentions = [people[n.lower()] for n in MENTION.findall(text) if n.lower() in people]
    f.chatter = bool(CHATTER.search(body))
    f.no_deadline = bool(NOT_A_DEADLINE.search(body))
    lead = re.sub(r"^(?:@?\w+[,:]\s+)", lambda m: "" if m.group(0).strip("@,: ").lower() in people else m.group(0), body)
    f.agree = (bool(AGREE_START.match(lead)) or any(AGREE_ANY.search(s) for _, s in f.sents)) and not AGREE_NOT.search(body)
    f.disagree = bool(DISAGREE.search(lead))
    if f.disagree:
        f.agree = False
    f.accept = bool(ACCEPT_START.match(lead))
    claim = CLAIM.search(body)
    if claim:
        end = re.search(r"[.!?](?:\s|$)", body[claim.end():])
        f.claim = body[claim.start(): claim.end() + (end.end() if end else len(body))].strip()
        f.claim_dates = [d for d in f.dates if d.start >= claim.start() and is_due(d, f.claim)]
    f.takeover = bool(TAKEOVER.search(body))
    f.correction = bool(CORRECTION.search(body))
    f.decision = bool(DECISION.search(body))
    f.reversal = bool(REVERSAL.search(body))
    cancel = CANCEL.search(body)
    if cancel and OFF_PERSON.search(body[max(0, cancel.start() - 30):cancel.end()]):
        cancel = None
    if cancel:
        f.cancel = next((s for o, s in f.sents if o <= cancel.start() < o + len(s) + 2), body)
        # the clause that holds the cue names what was called off
        start = max(body.rfind(c, 0, cancel.start()) for c in ",;:.!?") + 1
        stop = min([i for i in (body.find(c, cancel.end()) for c in ",;.!?") if i >= 0] or [len(body)])
        f.cancel_clause = body[start:stop].strip()
    move = MOVE.search(body)
    if move and any(d.start >= move.start() for d in f.dates):
        f.move = move
    for _, s in f.sents:
        is_q = s.rstrip().endswith(("?", "\u061f"))
        addressee = re.match(r"^(\w+),\s", s) or re.match(r"^(\w+)\s+(?:can|could|would) you\b", s)
        to = None
        if f.mentions:
            to = f.mentions[0]
        elif addressee and addressee.group(1).lower() in people:
            to = people[addressee.group(1).lower()]
        if PROPOSE.search(s) and not PROPOSE_NOT.search(s) and not f.proposal:
            f.proposal = s
        elif REQUEST.search(s) and not f.request and (to or "?" in s or re.search(r"\bcan the\b|\bcould the\b", s, re.I)):
            f.request, f.request_to = s, to
        elif is_q and to and not INFO_QUESTION_START.match(re.sub(r"^\w+,\s*", "", s)) and not f.request:
            f.request, f.request_to = s, to
        elif to and addressee and not f.request and not is_q:
            f.request, f.request_to = s, to  # "Omar, same 150." is an instruction to Omar
        elif is_q and not f.question:
            sdates = [d for d in f.dates if d.start >= body.find(s)]
            if sdates and not INFO_QUESTION_START.match(s) and not f.proposal:
                f.proposal, f.date_proposal = s, True
            else:
                f.question = s
    f.info_question = bool(f.question) and not f.proposal and not f.request
    if f.proposal and not f.date_proposal:
        f.date_proposal = bool(f.dates) and not f.move
    return f


# ---------------------------------------------------------------- extractor


@dataclass
class OpenProposal:
    item: Item
    msg: Message
    kind: str  # plain | date | move
    value: object = None  # date for date/move proposals
    target: Item | None = None  # deadline a move proposal would change
    closed: bool = False


@dataclass
class PendingRequest:
    msg: Message
    to: str | None
    text: str
    takeover: bool
    dates: list[DateMention]
    done: bool = False


class Extractor:
    def __init__(self, thread: Thread):
        self.thread = thread
        self.by_id = thread.by_id()
        first_names: dict[str, str] = {}
        for m in thread.messages:
            first_names.setdefault(m.author.split()[0].lower(), m.author)
        self.people = first_names
        self.items: list[Item] = []
        self.proposals: list[OpenProposal] = []
        self.requests: list[PendingRequest] = []
        self.features: dict[str, Features] = {}
        self.counter: dict[str, int] = {}

    # -- helpers
    def new_item(self, type_: str, status: str, label: str, msg: Message, **kw) -> Item:
        self.counter[type_] = self.counter.get(type_, 0) + 1
        item = Item(f"{type_}-{self.counter[type_]}", type_, status, short(label), msg.id, [msg.id], **kw)
        item.keywords = keywords(label)
        self.items.append(item)
        return item

    def context_keywords(self, msg: Message) -> set[str]:
        """Keywords of a message plus the author's message just before it (people post in bursts)."""
        words = keywords(msg.text)
        prev = self.thread.messages[msg.idx - 2] if msg.idx > 1 else None
        if prev and prev.author == msg.author and msg.ts - prev.ts <= timedelta(minutes=10):
            words |= keywords(prev.text)
        return words

    def deadlines(self) -> list[Item]:
        return [i for i in self.items if i.type == "deadline" and i.status == "current"]

    def find_target(self, msg: Message, words: set[str], candidates: list[Item], old_dates=(), min_overlap=1):
        best, best_score = None, 0.0
        for c in candidates:
            score = 0.0
            if msg.reply_to and msg.reply_to in c.source_ids:
                score += 5
            if c.date and c.date in old_dates:
                score += 4
            # a shared code (WH-09, S-03, DSP-2026-00413) names the same thing: it counts twice
            overlap = sum(2 if CODE.fullmatch(w) else 1 for w in words & c.keywords)
            if overlap >= min_overlap:
                score += 2 * overlap
            if score > 0:
                score += self.thread.messages.index(self.by_id[c.source_ids[-1]]) / 10000
            if score > best_score:
                best, best_score = c, score
        return best

    def open_proposal_for(self, msg: Message) -> OpenProposal | None:
        if msg.reply_to:
            for p in self.proposals:
                if p.msg.id == msg.reply_to and not p.closed:
                    return p
            return None
        for p in reversed(self.proposals):
            if p.closed or p.msg.author == msg.author:
                continue
            if msg.idx - p.msg.idx <= 8 and msg.ts - p.msg.ts <= timedelta(hours=24):
                return p
            break
        return None

    # -- state changes
    def set_deadline(self, msg: Message, mention: DateMention, label: str, kind: str = "set",
                     origin: Message | None = None, merge: bool = True) -> Item:
        words = keywords(msg.text)
        for d in self.deadlines():
            # The same date again is the same deadline when the message is about the same
            # thing (shared words, or a reply to it) or too short to set up something new.
            related = len(words & d.keywords) >= 2 or msg.reply_to in d.source_ids or len(msg.text.split()) <= 10
            if merge and d.date == mention.value and related:
                d.add_source(msg.id)
                d.keywords |= words
                d.history.append(Version("mentioned", msg.id, msg.author, mention.value.isoformat(), short(msg.text)))
                return d
        origin = origin or msg
        item = self.new_item("deadline", "current", label, origin, date=mention.value)
        item.keywords |= keywords(origin.text) | words
        item.add_source(msg.id)
        item.history.append(Version(kind, origin.id, origin.author, mention.value.isoformat(), short(origin.text)))
        if origin is not msg:
            item.history.append(Version("agreed", msg.id, msg.author, mention.value.isoformat(), short(msg.text)))
        return item

    def change_deadline(self, item: Item, msg: Message, value, kind: str, agreed_by: Message | None = None):
        item.date = value
        item.add_source(msg.id)
        item.keywords |= keywords(msg.text)
        item.history.append(Version(kind, msg.id, msg.author, value.isoformat(), short(msg.text)))
        if agreed_by:
            item.add_source(agreed_by.id)
            item.history.append(Version("agreed", agreed_by.id, agreed_by.author, value.isoformat(), short(agreed_by.text)))

    def make_decision(self, item: Item, msg: Message, words: set[str]):
        """Turn a proposal (or a new item) into a decision in force; reverse the one it replaces."""
        reverse, best = None, 0
        cue = bool(REVERSAL.search(" ".join([item.label, msg.text])))
        for d in self.items:
            if d is item or d.type != "decision" or d.status != "in_force":
                continue
            overlap = len(words & d.keywords)
            if ((overlap >= 1 and cue) or overlap >= 4) and overlap > best:
                reverse, best = d, overlap
        if reverse:
            reverse.status = "reversed"
            reverse.target = item.id
            reverse.add_source(msg.id)
            reverse.history.append(Version("reversed", item.origin_id, self.by_id[item.origin_id].author,
                                           item.label, short(self.by_id[item.origin_id].text)))
            item.history.append(Version("reversed", item.origin_id, self.by_id[item.origin_id].author,
                                        f"replaces: {reverse.label}", ""))

    def add_owner(self, msg: Message, owner: str, label: str, origin: Message, takeover: bool, words: set[str]):
        if takeover:
            for o in self.items:
                if o.type == "owner" and o.status == "current" and o.owner != owner and words & o.keywords:
                    o.status = "superseded"
                    o.add_source(msg.id)
                    o.history.append(Version("reassigned", msg.id, msg.author, owner, short(msg.text)))
        item = self.new_item("owner", "current", label, origin, owner=owner)
        item.keywords |= words
        item.add_source(msg.id)
        item.history.append(Version("set", origin.id, origin.author, owner, short(origin.text)))
        if origin is not msg:
            item.history.append(Version("agreed", msg.id, msg.author, owner, short(msg.text)))
        return item

    # -- one message
    def apply(self, msg: Message) -> None:
        f = describe(msg, self.people)
        self.features[msg.id] = f
        words = keywords(msg.text)
        consumed_dates = False

        # 1. correction of the author's own recent date ("sorry, I meant the 18th")
        if f.correction and f.dates:
            recent = [d for d in self.deadlines()
                      if self.by_id[d.origin_id].author == msg.author or msg.reply_to in d.source_ids]
            recent = [d for d in recent if msg.idx - self.by_id[d.source_ids[-1]].idx <= 5]
            if recent:
                target = recent[-1]
                self.change_deadline(target, msg, f.dates[0].value, "corrected")
                consumed_dates = True

        # 2. cancellation
        if f.cancel:
            replied = self.by_id.get(msg.reply_to) if msg.reply_to else None
            prior = next((i for i in self.items if i.type == "cancellation" and replied and replied.id in i.source_ids), None)
            if prior:
                prior.add_source(msg.id)
            else:
                cancel_words = keywords(f.cancel_clause)
                kept = set()
                for _, s in f.sents:
                    if STILL.search(s):
                        kept |= keywords(s)
                candidates = [i for i in self.items
                              if i.type in ("deadline", "owner") and i.status == "current" and not (kept & i.keywords)]
                in_sentence = {d.value for d in find_dates(f.cancel_clause, msg.day)}
                target = self.find_target(msg, cancel_words, candidates, old_dates=in_sentence, min_overlap=2)
                item = self.new_item("cancellation", "cancelled", f.cancel, msg)
                item.history.append(Version("cancelled", msg.id, msg.author, "", short(msg.text)))
                if target:
                    item.target = target.id
                    item.label = short(f"{target.label}")
                    target.status = "cancelled"
                    target.add_source(msg.id)
                    target.history.append(Version("cancelled", msg.id, msg.author, "", short(msg.text)))
                    for o in self.items:  # a task called off takes its owner with it
                        if o.type == "owner" and o.status == "current" and target.origin_id in o.source_ids:
                            o.status = "cancelled"
                consumed_dates = True

        # 3. a decision announced as made
        if f.decision:
            item = self.new_item("decision", "in_force", next((s for _, s in f.sents if DECISION.search(s)), msg.text), msg)
            item.keywords |= self.context_keywords(msg)
            item.history.append(Version("set", msg.id, msg.author, "announced", short(msg.text)))
            self.make_decision(item, msg, self.context_keywords(msg))
            consumed_dates = True

        # 4. agreement or disagreement with an open proposal
        agreed_proposal = None
        if (f.agree or f.disagree) and not f.proposal:
            p = self.open_proposal_for(msg)
            if p and f.disagree:
                p.closed = True
                p.item.add_source(msg.id)
                p.item.history.append(Version("rejected", msg.id, msg.author, "", short(msg.text)))
                consumed_dates = True
            elif p:
                agreed_proposal = p
                self.accept_proposal(p, msg, f)
                consumed_dates = True

        # 5. acceptance of a pending request, or a claim of a task
        accepted = None
        for r in reversed(self.requests):
            if r.done or msg.author == r.msg.author or (r.to and r.to != msg.author):
                continue
            if msg.idx - r.msg.idx > 12 or (msg.reply_to and msg.reply_to != r.msg.id):
                continue
            if f.claim or (f.accept and r.to):
                accepted = r
                break
        if accepted:
            accepted.done = True
            origin = msg if f.claim else accepted.msg
            label = accepted.text if not f.claim or ANAPHORA.search(f.claim[:40]) else f.claim
            self.add_owner(msg, msg.author, label, origin, accepted.takeover or f.takeover,
                           keywords(accepted.text) | words)
            if not f.move and not f.no_deadline:
                if f.claim and f.claim_dates:
                    d = f.claim_dates[0]
                    same = [x for x in self.deadlines() if x.date == d.value and words & x.keywords]
                    self.set_deadline(msg, d, f.claim, merge=bool(same))
                elif f.dates and not consumed_dates:
                    self.set_deadline(msg, f.dates[0], f"{accepted.text} ({short(msg.text, 60)})")
                elif accepted.dates:
                    self.set_deadline(msg, accepted.dates[0], accepted.text, origin=accepted.msg)
                consumed_dates = True
        elif f.claim and not f.chatter:
            target_msg = self.by_id.get(msg.reply_to) if msg.reply_to else None
            label = f.claim
            if ANAPHORA.search(f.claim[:40]) and target_msg and len(f.claim) < 60:
                label = f"{target_msg.text} ({f.claim.strip()})"
            elif ANAPHORA.search(f.claim[:40]) and len(f.claim) < 60:
                label = msg.text
            self.add_owner(msg, msg.author, label, msg, f.takeover, words | (keywords(target_msg.text) if target_msg else set()))
            if f.claim_dates and not f.move:
                d = f.claim_dates[0]
                same = [x for x in self.deadlines() if x.date == d.value and words & x.keywords]
                self.set_deadline(msg, d, f.claim, merge=bool(same))
                consumed_dates = True

        # 6. a move stated as fact ("Racking pushed to Monday", "Monday instead of today")
        if f.move and not f.proposal and not consumed_dates:
            new, old = self.move_dates(f)
            target = self.find_target(msg, self.move_words(f), self.deadlines(), old_dates=old) \
                or self.find_target(msg, words, self.deadlines(), old_dates=old)
            if target is None and ANAPHORA.search(msg.text):
                recent = [d for d in self.deadlines() if msg.idx - self.by_id[d.source_ids[-1]].idx <= 10]
                target = recent[-1] if recent else None
            if target and target.date != new.value:
                self.change_deadline(target, msg, new.value, "moved")
            elif not target:
                self.set_deadline(msg, new, msg.text)
            consumed_dates = True

        # 7. a new proposal
        if f.proposal and not f.disagree and not f.chatter:
            kind, value, target = "plain", None, None
            if f.move:
                new, old = self.move_dates(f)
                target = self.find_target(msg, self.move_words(f), self.deadlines(), old_dates=old) \
                    or self.find_target(msg, words, self.deadlines(), old_dates=old)
                if target:
                    kind, value = "move", new.value
            if kind == "plain" and f.dates:
                fresh = [d for d in f.dates if d.value not in {x.date for x in self.deadlines()}]
                if fresh:
                    kind, value = "date", fresh[0].value
            label = f.proposal if len(f.proposal) > 50 else msg.text
            item = self.new_item("proposal", "not_agreed", label, msg)
            item.keywords |= self.context_keywords(msg)
            item.history.append(Version("proposed", msg.id, msg.author,
                                        value.isoformat() if value else "", short(msg.text)))
            if target:
                item.target = target.id
            self.proposals.append(OpenProposal(item, msg, kind, value, target))
            consumed_dates = True

        # 8. a new request ("@Rana can you get freight quotes?")
        if f.request and not f.chatter:
            req_start = MENTION.sub(lambda m: m.group(1), msg.text).find(f.request)
            req_dates = [d for d in f.dates if req_start <= d.start < req_start + len(f.request)]
            self.requests.append(PendingRequest(msg, f.request_to, f.request, f.takeover, req_dates))
            # dates outside the request sentence ("S-03 goes tomorrow. Omar, same 150.") still count
            consumed_dates = consumed_dates or bool(req_dates)

        # 9. a date stated as plan or fact
        if f.dates and not consumed_dates and not f.chatter and not f.no_deadline and not f.disagree \
                and not f.question and not agreed_proposal:
            primary = self.primary_date(msg.text, f.dates)
            sentence = next((s for o, s in f.sents if o <= primary.start < o + len(s) + 2), msg.text)
            if is_due(primary, sentence):
                self.set_deadline(msg, primary, sentence)

    @staticmethod
    def move_words(f: Features) -> set[str]:
        """Keywords of the sentence that holds the move cue: it names what moved."""
        s = next((s for o, s in f.sents if o <= f.move.start() < o + len(s) + 2), "")
        return keywords(s)

    @staticmethod
    def move_dates(f: Features):
        """New and old dates of a move. "Monday instead of today": new comes first."""
        if f.move.group(0).lower().startswith("instead"):
            before = [d for d in f.dates if d.start < f.move.start()]
            after = [d for d in f.dates if d.start >= f.move.start()]
            if before:
                return before[-1], {d.value for d in after}
        new = next(d for d in f.dates if d.start >= f.move.start())
        return new, {d.value for d in f.dates if d is not new}

    def primary_date(self, text: str, dates: list[DateMention]) -> DateMention:
        for d in dates:
            before = text[max(0, d.start - 14):d.start].lower()
            if re.search(r"\b(?:by|due|before|until|on|for|is|deadline)\s+(?:the\s+)?$", before):
                return d
        return dates[0]

    def accept_proposal(self, p: OpenProposal, msg: Message, f: Features):
        p.closed = True
        if p.kind == "move" and p.target is not None and p.target.status == "current":
            self.change_deadline(p.target, p.msg, p.value, "moved", agreed_by=msg)
            self.items.remove(p.item)
        elif p.kind == "date":
            proposed = next(d for d in describe(p.msg, self.people).dates if d.value == p.value)
            # "ok, Tuesday works" agrees to "Tuesday 28 April": a bare weekday in the reply
            # points back at the proposed day, only an explicit date in the reply overrides it
            explicit = [d for d in f.dates if d.kind in ("explicit", "ordinal")]
            value = explicit[0] if explicit else proposed
            self.set_deadline(msg, value, p.item.label, origin=p.msg)
            self.items.remove(p.item)
        else:
            item = p.item
            item.type, item.status = "decision", "in_force"
            self.counter["decision"] = self.counter.get("decision", 0) + 1
            item.id = f"decision-{self.counter['decision']}"
            item.add_source(msg.id)
            item.history.append(Version("agreed", msg.id, msg.author, "", short(msg.text)))
            self.make_decision(item, p.msg, item.keywords)

    # -- second pass
    def find_unanswered(self) -> None:
        msgs = self.thread.messages
        for i, q in enumerate(msgs):
            f = self.features[q.id]
            if not f.info_question or f.chatter:
                continue
            if any(m.reply_to == q.id and m.author != q.author for m in msgs[i + 1:]):
                continue
            qwords = keywords(f.question or "")
            answered = False
            seen = 0
            for m in msgs[i + 1:]:
                if m.ts - q.ts > timedelta(hours=4) or seen >= 4:
                    break
                seen += 1
                mf = self.features[m.id]
                if m.author == q.author or (m.reply_to and m.reply_to != q.id) or mf.question or mf.chatter:
                    continue
                if f.mentions and m.author not in f.mentions:
                    continue
                if ANSWER_START.match(m.text.strip()) or len(qwords & keywords(m.text)) >= 2:
                    answered = True
                break
            if not answered:
                item = self.new_item("question", "unanswered", f.question or q.text, q)
                item.history.append(Version("set", q.id, q.author, "", short(q.text)))

    def run(self) -> list[Item]:
        for msg in self.thread.messages:
            self.apply(msg)
        self.find_unanswered()
        return self.items


def extract(thread: Thread) -> list[Item]:
    return Extractor(thread).run()
