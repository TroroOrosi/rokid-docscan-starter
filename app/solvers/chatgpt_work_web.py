"""Work UI adapter sharing Chat's durable send/receipt journal.

The venue process runs beside Termux Chromium. Original images travel in ZIPs;
a completed upload is transport evidence, not proof of visual readability.
Work's plain-Markdown final message has different semantics from Chat's turns.
"""

from __future__ import annotations

import json
import os
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
import re
import sys
import tempfile
import threading
import time
import unicodedata
from urllib.parse import urlsplit

from . import chatgpt_web as chat


MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 96 * 1024 * 1024
FILE_INPUT_SEL = 'input[type="file"][multiple]:not([disabled]):is([accept=""],:not([accept]))'
COMPOSER_SEL = (chat.COMPOSER_SEL + ', div[role="textbox"][contenteditable="true"]'
                '[aria-label="Work with ChatGPT"]')
USER_SEL = ('div[data-user-message-bubble="true"], '
            'div.rich-text-user-turn[data-markdown-text-tone="user-message"]'
            ':not([data-user-message-bubble="true"] *)')
ASSISTANT_SEL = 'div[data-markdown-text-style="assistant-message"]'
MODEL = "GPT-6.1 Sol"


@dataclass(frozen=True)
class _Settings:
    model: str
    power: int
    effort: str
    speed: str


def _normalise(value):
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKC", value).lower())


def _requested_settings(settings=None):
    values = settings if settings is not None else {
        "model": os.environ.get("ROKID_WORK_MODEL") or MODEL,
        "effort": os.environ.get("ROKID_WORK_EFFORT") or "xhigh",
        "speed": os.environ.get("ROKID_WORK_SPEED") or "fast",
    }
    if (not isinstance(values, dict) or set(values) != {"model", "effort", "speed"}
            or any(not isinstance(value, str) or not value.strip() for value in values.values())):
        raise chat.ChatGptWebModelMismatch("Work requested settings are invalid; nothing sent")
    model = values["model"].strip()
    if not re.fullmatch(r"gpt\d+[a-z0-9]+", _normalise(model)):
        raise chat.ChatGptWebModelMismatch("Work requires an explicit model family/version/variant")
    effort = {"light": (0, "Light"), "medium": (1, "Medium"), "high": (2, "High"),
              "xhigh": (3, "Extra High"), "extrahigh": (3, "Extra High")}.get(_normalise(values["effort"]))
    speed = _normalise(values["speed"])
    if effort is None or speed not in ("fast", "standard"):
        raise chat.ChatGptWebModelMismatch("Work effort/speed has no validated control mapping; nothing sent")
    return _Settings(model, *effort, speed)

# Only public controls are returned. A checked Default radio plus a Sol summary
# is deliberately insufficient: Default may choose a different model later.
_CONTROLS_JS = r"""((action, requested) => {
  const visible = e => !!e && e.getClientRects().length > 0;
  const norm = s => (s || '').normalize('NFKC').toLowerCase().replace(/[^a-z0-9]/g, '');
  const label = e => (e.getAttribute('aria-label') || e.innerText || '').trim();
  const enabled = e => !e.disabled && e.getAttribute('aria-disabled') !== 'true';
  const all = (selector, root=document) => [...root.querySelectorAll(selector)].filter(visible);
  const work = all('button[aria-pressed]').filter(e => norm(label(e)) === 'work');
  const triggers = all('button[aria-haspopup]').filter(e => {
    if (norm(e.getAttribute('aria-label')) === 'selectchatgptmodel') return true;
    const controlled = document.getElementById(e.getAttribute('aria-controls') || '');
    return !!controlled && !!controlled.querySelector('[role=menuitemradio], [role=radio], [role=option]') &&
      /model/i.test((e.getAttribute('aria-label') || '') + ' ' + (controlled.getAttribute('aria-label') || ''));
  });
  const menus = all('[role=menu], [role=listbox]').filter(e =>
    all('[role=menuitemradio], [role=radio], [role=option]', e).some(r => /^gpt\d/.test(norm(label(r)))));
  const menu = menus.length === 1 ? menus[0] : null;
  const radios = menu ? all('[role=menuitemradio], [role=radio], [role=option]', menu) : [];
  const matching = radios.filter(e => norm(label(e).split('\n')[0]) === norm(requested));
  const sliders = menu ? all('[role=slider]', menu) : [];
  const speed = menu ? all('[role=menuitemcheckbox]', menu).filter(e =>
    ['enablefastmode', 'enablestandardmode'].includes(norm(e.getAttribute('aria-label')))) : [];
  let acted = false;
  if (action === 'work' && work.length === 1 && enabled(work[0])) {
    work[0].click(); acted = true;
  } else if (['open', 'close'].includes(action) && triggers.length === 1 && enabled(triggers[0])) {
    triggers[0].click(); acted = true;
  } else if (action === 'model' && matching.length === 1 && enabled(matching[0])) {
    matching[0].click(); acted = true;
  } else if (action === 'fast' && speed.length === 1 && enabled(speed[0]) &&
      speed[0].getAttribute('aria-checked') === 'false' && norm(label(speed[0])) === 'enablefastmode') {
    speed[0].click(); acted = true;
  } else if (action === 'standard' && speed.length === 1 && enabled(speed[0]) &&
      speed[0].getAttribute('aria-checked') === 'true' && norm(label(speed[0])) === 'enablestandardmode') {
    speed[0].click(); acted = true;
  } else if (['left', 'right'].includes(action) && sliders.length === 1 && enabled(sliders[0]) &&
      sliders[0].getAttribute('aria-valuemin') === '0' && sliders[0].getAttribute('aria-valuemax') === '5') {
    const key = action === 'right' ? 'ArrowRight' : 'ArrowLeft';
    sliders[0].focus();
    sliders[0].dispatchEvent(new KeyboardEvent('keydown', {key, code:key, bubbles:true})); acted = true;
  }
  const summary = menu ? all('[role=menuitem][aria-label="Select model"]', menu).map(e => e.innerText).join(' ') : '';
  return {acted, work_count:work.length, work_active:work.length === 1 && work[0].getAttribute('aria-pressed') === 'true',
    trigger_count:triggers.length, menu_count:menus.length, model_matches:matching.length,
    checked:radios.filter(e => e.getAttribute('aria-checked') === 'true' || e.getAttribute('aria-selected') === 'true').map(e => norm(label(e).split('\n')[0])),
    power:sliders.length === 1 ? {value:sliders[0].getAttribute('aria-valuenow'), min:sliders[0].getAttribute('aria-valuemin'), max:sliders[0].getAttribute('aria-valuemax')} : null,
    effort_text:summary + ' ' + (sliders.length === 1 ? sliders[0].getAttribute('aria-valuetext') || '' : ''),
    fast:speed.length === 1 && speed[0].getAttribute('aria-checked') === 'true' && norm(label(speed[0])) === 'enablestandardmode',
    standard:speed.length === 1 && speed[0].getAttribute('aria-checked') === 'false' && norm(label(speed[0])) === 'enablefastmode'};
})"""


def _controls(page, action="state", *, model=MODEL):
    return page.evaluate(f"{_CONTROLS_JS}({json.dumps(action)}, {json.dumps(model)})")


def _effort_matches(text, requested):
    tokens = re.findall(r"extra[ -]?high|\bxhigh\b|\bhigh\b|\bmedium\b|\blight\b|極高|超高", text, re.I)
    aliases = {"extrahigh": "extrahigh", "xhigh": "extrahigh", "high": "high", "medium": "medium", "light": "light"}
    actual = {"extrahigh" if token in ("極高", "超高") else aliases.get(_normalise(token)) for token in tokens}
    return actual == {_normalise(requested)}


def verify_work_model(page, *, select=False, requested_settings=None, sleep=time.sleep, now=time.monotonic) -> str:
    """Inspect actual radios, power and speed; only preparation changes values."""
    settings = requested_settings if isinstance(requested_settings, _Settings) else _requested_settings(requested_settings)
    model_key = _normalise(settings.model)

    def controls(action="state"):
        return _controls(page, action, model=settings.model)

    def read_until(predicate):
        deadline = now() + min(5.0, chat.READY_TIMEOUT_S)
        while True:
            state = controls()
            if predicate(state):
                return state
            if now() >= deadline:
                raise chat.ChatGptWebModelMismatch("Work controls did not confirm the requested model/settings")
            sleep(0.05)

    state = controls()
    if state["work_count"] != 1:
        raise chat.ChatGptWebModelMismatch("Work entry is missing or ambiguous")
    if not state["work_active"]:
        if not select or not controls("work")["acted"]:
            raise chat.ChatGptWebModelMismatch("Work is not selected")
        state = read_until(lambda s: s["work_active"])
    opened = verified = False
    try:
        if state["menu_count"] == 0:
            if not controls("open")["acted"]:
                raise chat.ChatGptWebModelMismatch("Work model control is missing or ambiguous")
            opened = True
        state = read_until(lambda s: s["menu_count"] > 0)
        if state["menu_count"] != 1 or state["model_matches"] != 1:
            raise chat.ChatGptWebModelMismatch("the requested Work model radio is missing or ambiguous")
        if state["checked"] != [model_key]:
            if not select or not controls("model")["acted"]:
                raise chat.ChatGptWebModelMismatch("the selected Work model differs from the sealed request")
            state = controls()
            if state["menu_count"] == 0:
                if not controls("open")["acted"]:
                    raise chat.ChatGptWebModelMismatch("could not inspect the selected Work model")
            state = read_until(lambda s: s["checked"] == [model_key])
        power = state["power"]
        if not power or power["min"] != "0" or power["max"] != "5" or power["value"] not in tuple(map(str, range(6))):
            raise chat.ChatGptWebModelMismatch("Work power control changed; nothing sent")
        for _ in range(abs(settings.power - int(power["value"]))):
            if not select:
                raise chat.ChatGptWebModelMismatch("Work power differs from the sealed request")
            current = int(state["power"]["value"])
            direction = "right" if current < settings.power else "left"
            if not controls(direction)["acted"]:
                raise chat.ChatGptWebModelMismatch("could not adjust Work power")
            state = read_until(lambda s: s["power"] is not None and int(s["power"]["value"]) == current + (1 if current < settings.power else -1))
        if not state[settings.speed]:
            if not select or not controls(settings.speed)["acted"]:
                raise chat.ChatGptWebModelMismatch("Work speed differs from the sealed request")
            state = read_until(lambda s: s[settings.speed])
        if (state["checked"] != [model_key] or state["power"] != {"value": str(settings.power), "min": "0", "max": "5"}
                or not _effort_matches(state["effort_text"], settings.effort) or not state["work_active"]):
            raise chat.ChatGptWebModelMismatch("Work model, effort and speed were not jointly confirmed")
        verified = True
        return settings.model + " / " + settings.effort + " / " + settings.speed.title()
    finally:
        if (opened or verified) and controls()["menu_count"] == 1:
            controls("close")


_REPLY_STATE_JS = r"""(batchId => {
  const empty = {found:false, ambiguous:false, streaming:false, reply:'', started:false};
  const userSelector = %s;
  const users = [...document.querySelectorAll(userSelector)].filter(e => e.getClientRects().length);
  const matches = users.filter(e => {
    const text = e.textContent || ''; const pos = text.lastIndexOf('Transfer receipt:');
    if (pos < 0) return false;
    try { return JSON.parse(text.slice(pos + 'Transfer receipt:'.length).trim()).batch_id === batchId; }
    catch { return false; }
  });
  if (matches.length !== 1) return {...empty, ambiguous:matches.length > 1};
  const user = matches[0]; const main = user.closest('main');
  if (!main) return empty;
  const regions = [...main.querySelectorAll('[role=region][aria-label="Conversation"]')].filter(e => e.contains(user));
  if (regions.length > 1) return {...empty, ambiguous:true};
  const scope = regions[0] || main;
  const ownUsers = users.filter(e => scope.contains(e));
  if (ownUsers.at(-1) !== user) return empty;
  const after = e => !!(user.compareDocumentPosition(e) & Node.DOCUMENT_POSITION_FOLLOWING);
  const assistants = [...scope.querySelectorAll('div[data-markdown-text-style="assistant-message"]')].filter(after);
  const final = assistants.filter(e => {
    const owner = e.closest('[data-local-conversation-final-assistant="true"]');
    return owner && !owner.contains(user) && !owner.querySelector(userSelector);
  });
  const streaming = [...main.querySelectorAll('button[aria-label="Stop"], [data-testid="stop-button"]')].some(e => e.getClientRects().length);
  return {found:true, ambiguous:final.length > 1, streaming, started:streaming || assistants.length > 0,
    reply:final.length === 1 ? (final[0].textContent || '').trim() : ''};
})""" % json.dumps(USER_SEL)


def work_reply_state(page, batch_id):
    """Read only the final assistant following this exact transfer marker."""
    return page.evaluate(f"{_REPLY_STATE_JS}({json.dumps(batch_id)})")


def _wait_for_reply(page, batch_id, *, expect, on_chat_url=None, timeout_s=None,
                    poll_s=None, sleep=time.sleep, now=time.monotonic):
    deadline = now() + (chat.TIMEOUT_S if timeout_s is None else timeout_s)
    started = now()
    url_saved = False
    gone = 0
    while now() < deadline:
        if not url_saved and _conversation_id(chat._url_of(page)):
            if on_chat_url is not None:
                on_chat_url(chat._url_of(page))
            url_saved = True
        state = work_reply_state(page, batch_id)
        if state["ambiguous"]:
            raise chat.ChatGptWebError("Work task/final is ambiguous; no automatic resend")
        if state["streaming"]:
            gone = 0
        else:
            gone += 1
            reply = state["reply"]
            if reply and chat._complete_json(reply, expect):
                try:
                    if chat.extract_json(reply).get("batch_id") == batch_id:
                        return reply
                except (ValueError, AttributeError):
                    pass
            if reply and gone >= chat.SETTLE_POLLS:
                if chat._limited(reply):
                    raise chat.ChatGptWebRateLimit("the recorded Work task received a usage limit")
                raise chat.ChatGptWebError("Work final did not contain this batch's complete JSON")
        if not state["started"] and now() - started > chat.REPLY_START_S:
            raise chat.ChatGptWebError("the recorded Work task did not start; no automatic resend")
        sleep(chat.POLL_S if poll_s is None else poll_s)
    raise chat.ChatGptWebError("Work task did not finish; no automatic resend")


def _conversation_id(url):
    try:
        parsed = urlsplit(url or "")
        match = re.fullmatch(r"/c/([A-Za-z0-9-]{8,128})/?", parsed.path)
        return match[1] if parsed.scheme == "https" and parsed.netloc == "chatgpt.com" and match else None
    except ValueError:
        return None


_UPLOAD_STATE_JS = r"""(names => {
  const visible = e => e.getClientRects().length > 0;
  const composers = [...document.querySelectorAll(%s)].filter(visible);
  if (composers.length !== 1) return {ready:false, ambiguous:true, counts:[], error:false};
  const scope = composers[0].closest('form') || composers[0].closest('main');
  if (!scope) return {ready:false, ambiguous:true, counts:[], error:false};
  const cards = [...scope.querySelectorAll('span.truncate')].filter(e => !e.querySelector('span.truncate'));
  const counts = names.map(name => cards.filter(e => e.textContent.trim() === name).length);
  const error = [...scope.querySelectorAll('[role=alert], [data-state=error]')].some(visible);
  const busy = [...scope.querySelectorAll('[role=progressbar], [aria-busy=true], [data-state=uploading]')].some(visible);
  const sends = [...scope.querySelectorAll('button[data-testid="send-button"], button[type="submit"][aria-label="Send prompt"], button[type="submit"][aria-label="Send"]')].filter(visible);
  return {counts, error, ambiguous:false, ready:!busy && !error && counts.every(n => n === 1) &&
    sends.length === 1 && !sends[0].disabled && sends[0].getAttribute('aria-disabled') !== 'true'};
})""" % json.dumps(COMPOSER_SEL)


def _shared_filesystem(endpoint):
    return (os.name == "posix" and sys.executable.startswith("/data/data/com.termux/files/usr/")
            and urlsplit(endpoint).hostname in ("127.0.0.1", "localhost", "::1"))


def attach_work_files(page, files, *, endpoint, timeout_s=None, poll_s=None, sleep=time.sleep, now=time.monotonic):
    names = [item["name"] for item in files]
    if (not files or len(files) > 20 or len(names) != len(set(names))
            or any(not isinstance(name, str) or not name or Path(name).name != name or "/" in name or "\\" in name or "\0" in name for name in names)
            or any(not isinstance(item["buffer"], bytes) or not item["buffer"] or len(item["buffer"]) > MAX_FILE_BYTES for item in files)
            or any(item.get("mimeType") != "application/zip" and not item.get("mimeType", "").startswith("audio/") for item in files)
            or sum(len(item["buffer"]) for item in files) > MAX_TOTAL_BYTES):
        raise chat.ChatGptWebAttachmentFailed("Work source files exceed the bounded attachment contract")
    target = page.locator(FILE_INPUT_SEL)
    if target.count() != 1:
        raise chat.ChatGptWebAttachmentFailed("Work generic file input is missing or ambiguous")
    state_js = f"{_UPLOAD_STATE_JS}({json.dumps(names)})"
    state = page.evaluate(state_js)
    if state["ambiguous"] or state["error"] or any(state["counts"]):
        raise chat.ChatGptWebAttachmentFailed("Work composer already has these files or an upload error")
    # Keep private local files alive until the remote upload is confirmed.
    with tempfile.TemporaryDirectory(prefix="rokid-work-upload-") as directory:
        if _shared_filesystem(endpoint):
            os.chmod(directory, 0o700)
            paths = []
            for item in files:
                path = Path(directory) / item["name"]
                with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
                    stream.write(item["buffer"])
                paths.append(str(path))
            target.set_input_paths(paths)
        else:
            target.set_input_files(files)
        deadline = now() + (chat.UPLOAD_TIMEOUT_S if timeout_s is None else timeout_s)
        while True:
            state = page.evaluate(state_js)
            if state["error"] or state["ambiguous"] or any(n > 1 for n in state["counts"]):
                raise chat.ChatGptWebAttachmentFailed("Work file upload failed or became ambiguous")
            if state["ready"]:
                return True
            if now() >= deadline:
                raise chat.ChatGptWebAttachmentFailed("Work files did not finish uploading; nothing sent")
            sleep(chat.POLL_S if poll_s is None else poll_s)


_SEND_JS = r"""((click, expected) => {
  const composers = [...document.querySelectorAll(%s)].filter(e => e.getClientRects().length);
  const norm = text => (text || '').replace(/\s+/g, ' ').trim();
  if (composers.length !== 1 || norm(composers[0].innerText) !== norm(expected)) return false;
  const form = composers[0].closest('form');
  if (!form) return false;
  const buttons = [...form.querySelectorAll('button[data-testid="send-button"], button[type="submit"][aria-label="Send prompt"], button[type="submit"][aria-label="Send"]')].filter(e => e.getClientRects().length);
  if (buttons.length !== 1 || buttons[0].disabled || buttons[0].getAttribute('aria-disabled') === 'true') return false;
  if (click) buttons[0].click();
  return true;
})""" % json.dumps(COMPOSER_SEL)


def _pending_work_send(guard):
    """Identify one journal-owned Work batch without trusting a reply body."""
    status = guard.status()
    if status["state"] != "uncertain":
        return None
    matches = [(key, entry) for key, entry in chat._read_chats(guard.directory).items()
               if isinstance(entry, dict) and entry.get("pending") == status["request_id"]]
    if len(matches) != 1:
        return None
    key, entry = matches[0]
    transfer = entry.get("transfer")
    batch = transfer.get("pending") if isinstance(transfer, dict) else None
    if (not isinstance(key, str) or not re.fullmatch(r"session:[1-9][0-9]*:browser:[a-f0-9]{64}", key)
            or _conversation_id(entry.get("url")) is None or not isinstance(batch, dict)):
        return None
    stage = batch.get("stage", "single")
    names, digests, expect = (batch.get(field) for field in ("names", "digests", "expect"))
    if (stage not in ("single", "reading", "listening")
            or type(batch.get("number")) is not int or batch["number"] < 1
            or type(batch.get("final")) is not bool
            or any(type(batch.get(field)) is not int or batch[field] < 0 for field in ("users", "replies"))
            or not isinstance(names, list) or not 1 <= len(names) <= 20
            or any(not isinstance(name, str) or not name or "/" in name or "\\" in name or "\0" in name for name in names)
            or len(set(names)) != len(names) or not isinstance(digests, list) or len(digests) != len(names)
            or any(not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest) for digest in digests)
            or not isinstance(expect, list) or not expect or any(not isinstance(field, str) for field in expect)
            or (not batch["final"] and expect != ["received"])
            or (batch["final"] and "questions" not in expect)
            or any(not isinstance(transfer.get(field), list) for field in ("completed", "pages"))
            or not isinstance(entry.get("attached"), list)):
        return None
    identity = [key, batch["number"], names, digests]
    if stage != "single":
        identity.append(stage)
    if chat._digest(json.dumps(identity, separators=(",", ":")).encode()) != batch.get("id"):
        return None
    return key, stage, batch


class WorkWebClient(chat.ChatGptWebClient):
    """Work controls/final reader; BrowserGuard and batch journal stay shared."""

    transfer_batch_bytes = chat.TRANSFER_BATCH_BYTES

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._requested = ContextVar("work_requested_settings", default=None)
        self._observed = threading.local()

    def complete(self, *, requested_settings=None, **kwargs):
        token = self._requested.set(_requested_settings(requested_settings))
        self._observed.conversation_id = None
        try:
            return super().complete(**kwargs)
        finally:
            self._requested.reset(token)

    def complete_json(self, *, requested_settings=None, **kwargs):
        return chat.extract_json(self.complete(requested_settings=requested_settings, **kwargs))

    @property
    def conversation_id(self):
        return getattr(self._observed, "conversation_id", _conversation_id(self._chat_url))

    def pending_work_owner(self):
        """Return only a unique Work owner; unknown/legacy sends stay blocked."""
        try:
            with chat.BrowserGuard() as guard:
                pending = _pending_work_send(guard)
                return {"chat_key": pending[0], "stage": pending[1]} if pending else None
        except chat.BrowserBusy as error:
            raise chat.ChatGptWebBusy("browser is busy; nothing sent") from error
        except (chat.BrowserGuardError, OSError, ValueError, TypeError, KeyError):
            return None

    def retire_expired_batch(self, *, chat_key, booklet_stage, expired_guard, sleep=time.sleep):
        """Read a stale owner's matching final/ACK and retire that send only.

        This does not enter complete/recover/ask: none of their preparation,
        model, attachment, next-batch or answer-sealing paths are reachable.
        """
        from .cdp import CdpError, connect_over_cdp  # noqa: PLC0415

        try:
            with chat.BrowserGuard() as guard:
                pending = _pending_work_send(guard)
                if not pending or pending[:2] != (chat_key, booklet_stage):
                    return False
                self._load_chat(guard, chat_key)
                batch = pending[2]
                with expired_guard():
                    pass  # Verify expiry and inactive ownership BEFORE browser reads.
                browser = connect_over_cdp(self.endpoint)
                try:
                    if not browser.contexts:
                        return False
                    pages = [page for page in browser.contexts[0].pages
                             if urlsplit(chat._url_of(page)).scheme == "https"
                             and urlsplit(chat._url_of(page)).netloc == "chatgpt.com"]
                    exact = [page for page in pages if chat._url_of(page) == self._chat_url]
                    choices = exact or pages
                    if len(choices) != 1:
                        return False
                    page = choices[0]
                    page.goto(self._chat_url, wait_until="domcontentloaded")
                    if chat._url_of(page) != self._chat_url:
                        return False
                    state = work_reply_state(page, batch["id"])
                    if not state["found"] or state["ambiguous"] or state["streaming"] or not state["reply"]:
                        return False
                    reply = state["reply"]
                    received = self._valid_batch(reply, batch)
                    if not received:
                        if not chat._limited(reply):
                            return False
                        try:
                            chat.extract_json(reply)
                        except ValueError:
                            pass
                        else:
                            return False  # A mismatched JSON answer is not a proven refusal.
                        for _ in range(max(0, chat.SETTLE_POLLS - 1)):
                            sleep(chat.POLL_S)
                            if work_reply_state(page, batch["id"]) != state:
                                return False
                    if work_reply_state(page, batch["id"]) != state:
                        return False
                    with expired_guard():
                        if received:
                            self._accept_batch(guard, reply, batch, self._pending)
                        else:
                            self._clear_refused_batch(guard, self._pending, self._chat_url)
                    return True
                finally:
                    browser.close()
        except chat.BrowserBusy as error:
            raise chat.ChatGptWebBusy("browser is busy; nothing sent") from error
        except (chat.BrowserGuardError, CdpError, chat.ChatGptWebError, OSError, ValueError, TypeError, KeyError):
            return False

    def _wait_for_composer(self, page, *, ready_timeout_s=None):
        return chat.wait_for_composer(page, ready_timeout_s=ready_timeout_s, composer_selector=COMPOSER_SEL)

    def _start_new_chat(self, page):
        return chat.start_new_chat(page, wait_composer=self._wait_for_composer)

    def _verify_model(self, page, *, select=False):
        return verify_work_model(page, select=select, requested_settings=self._requested.get())

    def _attach_images(self, page, images, *, files=None, audio=None, **kwargs):
        if images or audio:
            raise chat.ChatGptWebAttachmentFailed("Work expects original ZIP/audio file payloads")
        return attach_work_files(page, files or [], endpoint=self.endpoint, **kwargs)

    def _turn_counts(self, page):
        return page.locator(USER_SEL).count(), page.locator(ASSISTANT_SEL).count()

    def _send_and_read(self, page, text, *, composer, expect, before_submit, on_chat_url, on_model):
        try:
            receipt = json.loads(text.rsplit("\nTransfer receipt:\n", 1)[1])
            batch_id = receipt["batch_id"]
        except (ValueError, IndexError, KeyError) as error:
            raise chat.ChatGptWebBlocked("Work requires the durable booklet batch marker") from error
        composer = self._wait_for_composer(page)
        composer.click()
        composer.fill(text)
        on_model(self._verify_model(page))
        if " ".join(composer.inner_text().split()) != " ".join(text.split()):
            raise chat.ChatGptWebBlocked("Work draft changed before send; nothing sent")
        send = page.evaluate(f"{_SEND_JS}(false, {json.dumps(text)})")
        if not send:
            raise chat.ChatGptWebAttachmentFailed("Work send control is disabled or ambiguous")
        before_submit()
        # No Enter fallback: an unknown control must not turn into a blind send.
        if not page.evaluate(f"{_SEND_JS}(true, {json.dumps(text)})"):
            raise chat.ChatGptWebError("Work send control changed after journaling; no automatic resend")
        def observed(url):
            on_chat_url(url)
            self._observed.conversation_id = _conversation_id(url)

        return _wait_for_reply(page, batch_id, expect=expect, on_chat_url=observed)

    def _return_to_chat(self, page, url, *, reload):
        if _conversation_id(url) is None:
            raise chat.ChatGptWebChatLost("Work conversation address is invalid; nothing sent")
        return chat.return_to_chat(page, url, reload=reload, wait_composer=self._wait_for_composer)

    def _recover_locked(self, context, guard, *, expect, batch=None, sleep=time.sleep, now=time.monotonic):
        if not batch or not self._chat_url:
            return None
        page = chat.reuse_page(context)
        if _conversation_id(self._chat_url):
            self._return_to_chat(page, self._chat_url, reload=True)
        elif not _conversation_id(chat._url_of(page)):
            return None
        try:
            reply = _wait_for_reply(page, batch["id"], expect=expect, sleep=sleep, now=now)
        except chat.ChatGptWebRateLimit:
            if self._pending and self._transfer.get("pending") == batch:
                self._clear_refused_batch(guard, self._pending, chat._url_of(page))
            raise
        except chat.ChatGptWebError:
            return None
        if not self._valid_batch(reply, batch):
            return None
        if self._transfer.get("pending"):
            self._chat_url = chat._url_of(page)
            self._accept_batch(guard, reply, batch, self._pending)
        self._observed.conversation_id = _conversation_id(chat._url_of(page))
        return reply
