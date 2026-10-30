"""Work's measured controls and plain-Markdown final turn, on local HTML only."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import time

import pytest

from app.solvers import chatgpt_web, chatgpt_work_web as work
from app.solvers.cdp import connect_over_cdp


@pytest.fixture(scope="module")
def browser_page(tmp_path_factory):
    executable = next((p for p in [shutil.which("google-chrome"), shutil.which("chromium"),
                      "C:/Program Files/Google/Chrome/Application/chrome.exe"]
                       if p and Path(p).is_file()), None)
    if executable is None:
        pytest.skip("local Chromium is not installed; no browser is downloaded")
    directory = tmp_path_factory.mktemp("work-web-dom")
    fixture = directory / "fixture.html"
    fixture.write_text('<meta charset="utf-8"><body></body>', encoding="utf-8")
    process = subprocess.Popen([
        executable, "--headless", "--remote-debugging-port=0", "--disable-background-networking",
        "--disable-component-update", "--disable-sync", "--no-first-run", "--no-default-browser-check",
        "--host-resolver-rules=MAP * ~NOTFOUND", "--user-data-dir=" + str(directory / "profile"),
        fixture.as_uri(),
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    browser = None
    try:
        port_file = directory / "profile" / "DevToolsActivePort"
        deadline = time.monotonic() + 20
        while not port_file.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert port_file.exists(), "local Chromium did not expose its debugging port"
        port = int(port_file.read_text(encoding="utf-8").splitlines()[0])
        browser = connect_over_cdp(f"http://127.0.0.1:{port}")
        page = browser.contexts[0].pages[0]
        while time.monotonic() < deadline:
            if page.url == fixture.as_uri() and page.evaluate("document.readyState") == "complete":
                break
            time.sleep(0.05)
        assert page.url == fixture.as_uri() and page.evaluate("document.readyState") == "complete"
        yield page
    finally:
        if browser is not None:
            browser.close()
        process.terminate()
        process.wait(timeout=10)


@pytest.fixture
def page(browser_page):
    browser_page.evaluate("document.body.innerHTML = ''; true")
    return browser_page


@pytest.fixture(autouse=True)
def private_state(monkeypatch, tmp_path):
    from app import config

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(chatgpt_web, "POLL_S", 0.001)
    monkeypatch.setattr(chatgpt_web, "RETRY_BACKOFF_S", 0)
    monkeypatch.setattr(chatgpt_web, "TIMEOUT_S", 0.2)
    monkeypatch.setattr(chatgpt_web, "REPLY_START_S", 0.05)


def _controls(page, *, selected="Default", power=0, fast=False):
    page.evaluate("document.body.innerHTML = " + json.dumps(f'''
      <button aria-pressed="false" id="work" onclick="this.setAttribute('aria-pressed','true')">Work</button>
      <button aria-label="Select ChatGPT model" aria-haspopup="menu" aria-controls="models"
        aria-expanded="false" onclick="let m=document.getElementById('models'); m.hidden=!m.hidden;
        this.setAttribute('aria-expanded',String(!m.hidden))">GPT-6.1 Sol</button>
      <div role="menu" id="models" aria-label="Model" hidden>
        <div role="menuitemradio" aria-checked="{str(selected == 'Default').lower()}" id="default">Default</div>
        <div role="menuitemradio" aria-checked="{str(selected == 'GPT-6.1 Sol').lower()}" id="sol"
          onclick="document.querySelectorAll('[role=menuitemradio]').forEach(e=>e.setAttribute('aria-checked',String(e===this)))">GPT 6.1 Sol</div>
        <div role="menuitemradio" aria-checked="false" id="terra"
          onclick="document.querySelectorAll('[role=menuitemradio]').forEach(e=>e.setAttribute('aria-checked',String(e===this)))">GPT-6.1 Terra</div>
        <div role="menuitem" aria-label="Select model">GPT-6.1 Sol <span id="effort">{['Light', 'Medium', 'High', 'Extra High'][power]}</span></div>
        <span role="slider" tabindex="0" aria-valuenow="{power}" aria-valuemin="0" aria-valuemax="5"
          onkeydown="let n=Number(this.getAttribute('aria-valuenow'))+(event.key==='ArrowRight'?1:-1);
          this.setAttribute('aria-valuenow',n); document.getElementById('effort').textContent=['Light','Medium','High','Extra High'][n] || 'Other';"></span>
        <div role="menuitemcheckbox" aria-label="{'Enable standard mode' if fast else 'Enable fast mode'}"
          aria-checked="{str(fast).lower()}" onclick="let checked=this.getAttribute('aria-checked')!=='true';
          this.setAttribute('aria-checked',String(checked)); this.setAttribute('aria-label',checked?'Enable standard mode':'Enable fast mode')">More usage</div>
      </div>''') + "; true")


def test_preparation_selects_the_actual_radio_power_and_fast_controls(page):
    _controls(page)
    assert work.verify_work_model(page, select=True) == "GPT-6.1 Sol / Extra High / Fast"
    assert page.evaluate("document.getElementById('sol').getAttribute('aria-checked')") == "true"
    assert page.evaluate("document.getElementById('default').getAttribute('aria-checked')") == "false"
    assert page.evaluate("document.querySelector('[role=slider]').getAttribute('aria-valuenow')") == "3"
    assert page.evaluate("document.querySelector('[role=menuitemcheckbox]').getAttribute('aria-checked')") == "true"
    assert page.evaluate("document.getElementById('models').hidden") is True


def test_final_verification_does_not_fix_a_wrong_default_even_if_summary_names_sol(page):
    _controls(page, power=3, fast=True)
    page.evaluate("document.getElementById('work').setAttribute('aria-pressed','true')")
    with pytest.raises(chatgpt_web.ChatGptWebModelMismatch):
        work.verify_work_model(page)
    assert page.evaluate("document.getElementById('default').getAttribute('aria-checked')") == "true"
    assert page.evaluate("document.getElementById('models').hidden") is True


def test_unavailable_or_ambiguous_model_never_uses_an_ordinal_fallback(page):
    _controls(page, power=3, fast=True)
    page.evaluate("document.getElementById('sol').textContent='GPT-6.1 Luna'")
    with pytest.raises(chatgpt_web.ChatGptWebModelMismatch):
        work.verify_work_model(page, select=True)
    assert page.evaluate("document.getElementById('default').getAttribute('aria-checked')") == "true"


def test_work_environment_settings_and_changed_trigger_label_use_real_controls(page, monkeypatch):
    _controls(page, fast=True)
    page.evaluate("document.querySelector('button[aria-controls]').setAttribute('aria-label','Choose engine')")
    monkeypatch.setenv("ROKID_WORK_MODEL", "gpt_6.1_terra")
    monkeypatch.setenv("ROKID_WORK_EFFORT", "high")
    monkeypatch.setenv("ROKID_WORK_SPEED", "standard")
    assert work.verify_work_model(page, select=True) == "gpt_6.1_terra / High / Standard"
    assert page.evaluate("document.getElementById('terra').getAttribute('aria-checked')") == "true"
    assert page.evaluate("document.querySelector('[role=slider]').getAttribute('aria-valuenow')") == "2"
    assert page.evaluate("document.querySelector('[role=menuitemcheckbox]').getAttribute('aria-checked')") == "false"


def _conversation(page, *, later_user=False, final=True, stop=False):
    receipt = json.dumps({"batch_id": "own-batch", "questions": []})
    answer = json.dumps({"batch_id": "own-batch", "questions": [{"label": "1", "answer": "4"}]})
    page.evaluate("document.body.innerHTML = " + json.dumps(f'''
      <main><div data-local-conversation-final-assistant="true"><div data-markdown-text-style="assistant-message">{{"batch_id":"other","questions":[]}}</div></div></main>
      <main><div role="region" aria-label="Conversation">
        <div class="rich-text-user-turn" data-markdown-text-tone="user-message">Prompt with an example {{"questions":[]}}
          Transfer receipt:\n{receipt}</div>
        <div data-markdown-text-style="assistant-message">Working…</div>
        {'<div class="rich-text-user-turn" data-markdown-text-tone="user-message">A later, unrelated request</div>' if later_user else ''}
        <div {'data-local-conversation-final-assistant="true"' if final else ''}>
          <div data-markdown-text-style="assistant-message">{answer}</div>
        </div>
        {'<button aria-label="Stop">Stop</button>' if stop else ''}
      </div></main>''') + "; true")
    return answer


def test_plain_markdown_final_is_bound_to_own_user_and_main(page):
    answer = _conversation(page)
    state = work.work_reply_state(page, "own-batch")
    assert state["reply"] == answer and state["found"] is True and state["streaming"] is False
    assert page.locator("pre, code, [data-message-author-role]").count() == 0
    assert work.work_reply_state(page, "missing-batch")["reply"] == ""


@pytest.mark.parametrize("change", ["later_user", "final", "stop"])
def test_progress_or_a_later_request_cannot_be_accepted_as_own_final(page, change):
    _conversation(page, **{change: change != "final"})
    state = work.work_reply_state(page, "own-batch")
    assert state["reply"] == "" or state["streaming"] is True


def test_duplicate_own_marker_is_ambiguous_and_reads_no_answer(page):
    _conversation(page)
    page.evaluate("document.body.append(document.querySelectorAll('main')[1].cloneNode(true))")
    state = work.work_reply_state(page, "own-batch")
    assert state["ambiguous"] is True and state["reply"] == ""


def test_conversation_identity_is_observed_url_only():
    client = work.WorkWebClient()
    client._chat_url = "https://chatgpt.com/c/12345678-1234-1234-1234-123456789abc"
    assert client.conversation_id == "12345678-1234-1234-1234-123456789abc"
    for url in ("https://chatgpt.com.evil/c/123", "https://chatgpt.com/?next=/c/123", "http://chatgpt.com/c/123"):
        client._chat_url = url
        assert client.conversation_id is None


def _upload_composer(page):
    _controls(page, selected="GPT-6.1 Sol", power=3, fast=True)
    page.evaluate("""document.getElementById('work').setAttribute('aria-pressed','true');
      document.body.insertAdjacentHTML('beforeend', `<main><div role="region" aria-label="Conversation" id="conversation"></div>
      <form onsubmit="return false"><div id="work-composer" contenteditable="true" role="textbox" aria-label="Work with ChatGPT"></div>
      <input type="file" multiple id="files"><div id="cards"></div>
      <button type="submit" aria-label="Send" style="display:none" onclick="window.wrongSend=true">hidden Send</button>
      <button type="submit" aria-label="Send" id="send" disabled>Send</button></form></main>`);
      window.sent = 0; window.wrongSend = false; window.suppressFinal = false; window.uploadError = false; window.uploaded = [];
      document.getElementById('files').onchange = function() {
        for (const file of this.files) {
          window.uploaded.push(file.name);
          const card = document.createElement('span'); card.className='truncate'; card.textContent=file.name;
          document.getElementById('cards').append(card);
        }
        this.value=''; document.getElementById('send').disabled=false;
        if (window.uploadError) document.getElementById('cards').insertAdjacentHTML('beforeend','<div role="alert">Upload failed</div>');
      };
      window.finish = function() {
        const users = document.querySelectorAll('[data-user-message-bubble=true]');
        const text = users[users.length-1].textContent;
        const receipt = JSON.parse(text.split('Transfer receipt:\\n').at(-1));
        const reply = receipt.received ? receipt : {batch_id:receipt.batch_id,
          questions:[{question_id:'q1', label:'1', answer:'4', status:'ready', pages:[1], requires_audio:false}]};
        const owner = document.createElement('div'); owner.setAttribute('data-local-conversation-final-assistant','true');
        const final = document.createElement('div'); final.setAttribute('data-markdown-text-style','assistant-message');
        final.textContent=JSON.stringify(reply); owner.append(final); document.getElementById('conversation').append(owner);
      };
      document.getElementById('send').onclick = function() {
        window.sent++;
        const bubble = document.createElement('div'); bubble.setAttribute('data-user-message-bubble','true');
        const user = document.createElement('div');
        if (window.sent===1) {user.className='rich-text-user-turn'; user.setAttribute('data-markdown-text-tone','user-message');}
        else {user.className='text-size-chat whitespace-pre-wrap';}
        user.textContent=document.getElementById('work-composer').innerText;
        bubble.append(user); document.getElementById('conversation').append(bubble);
        document.getElementById('conversation').insertAdjacentHTML('beforeend','<div data-markdown-text-style="assistant-message">Working…</div>');
        document.getElementById('cards').innerHTML='';
        if (!window.suppressFinal) window.finish();
      }; true""")


def _payload(name="originals.zip", data=b"unmodified ZIP bytes"):
    return {"name": name, "mimeType": "application/zip", "buffer": data}


def test_attachment_confirmation_requires_the_card_and_enabled_send_not_input_files(page):
    _upload_composer(page)
    assert work.attach_work_files(page, [_payload()], endpoint="http://127.0.0.1:9222") is True
    assert page.evaluate("document.getElementById('files').files.length") == 0
    assert page.evaluate("window.sent") == 0


def test_failed_upload_or_oversized_original_never_submits(page, monkeypatch):
    _upload_composer(page)
    page.evaluate("window.uploadError = true")
    with pytest.raises(chatgpt_web.ChatGptWebAttachmentFailed, match="failed"):
        work.attach_work_files(page, [_payload()], endpoint="http://127.0.0.1:9222")
    _upload_composer(page)
    monkeypatch.setattr(work, "MAX_FILE_BYTES", 5)
    with pytest.raises(chatgpt_web.ChatGptWebAttachmentFailed, match="bounded"):
        work.attach_work_files(page, [_payload(data=b"123456")], endpoint="http://127.0.0.1:9222")
    assert page.evaluate("window.sent") == 0
    assert page.evaluate("document.getElementById('cards').children.length") == 0


@pytest.mark.parametrize("failed", [False, True])
def test_shared_filesystem_keeps_original_bytes_until_confirmed_and_cleans_private_files(monkeypatch, failed):
    monkeypatch.setattr(work, "_shared_filesystem", lambda endpoint: True)
    staged = []

    class SharedPage:
        attached = False

        def locator(self, selector):
            return self

        def count(self):
            return 1

        def set_input_paths(self, paths):
            staged.extend(Path(path) for path in paths)
            assert [path.read_bytes() for path in staged] == [b"original pixels in ZIP"]
            if work.os.name == "posix":
                assert staged[0].stat().st_mode & 0o777 == 0o600
                assert staged[0].parent.stat().st_mode & 0o777 == 0o700
            self.attached = True

        def evaluate(self, script):
            return {"counts": [int(self.attached)], "error": self.attached and failed,
                    "ambiguous": False, "ready": self.attached and not failed}

    page = SharedPage()
    if failed:
        with pytest.raises(chatgpt_web.ChatGptWebAttachmentFailed):
            work.attach_work_files(page, [_payload(data=b"original pixels in ZIP")], endpoint="http://127.0.0.1:9222")
    else:
        assert work.attach_work_files(page, [_payload(data=b"original pixels in ZIP")], endpoint="http://127.0.0.1:9222")
    assert staged and all(not path.exists() and not path.parent.exists() for path in staged)


class _VenueTab:
    """The local DOM's task URL, without any navigation to an external service."""

    def __init__(self, page):
        self.page = page
        self.navigations = []

    @property
    def url(self):
        return "https://chatgpt.com/c/12345678-1234-1234-1234-123456789abc" if self.page.evaluate("window.sent > 0") else "https://chatgpt.com/"

    def goto(self, url, **kwargs):
        self.navigations.append(url)

    def __getattr__(self, key):
        return getattr(self.page, key)


class _Context:
    def __init__(self, page):
        self.pages = [page]


def _booklet(client, page, files, **kwargs):
    return client._ask_with_retries(_Context(page), "Answer the entire paper", [],
        files=files, chat_key="work:local-fixture", expect=("questions",), booklet=True, **kwargs)


def _guard_state():
    from app.browser_guard import BrowserGuard

    with BrowserGuard() as guard:
        return guard.status()["state"]


def test_work_send_uses_durable_batch_then_restart_reads_it_without_upload_or_send(page, tmp_path):
    _upload_composer(page)
    tab = _VenueTab(page)
    first = json.loads(_booklet(work.WorkWebClient(), tab, lambda: [_payload()]))
    assert first["questions"][0]["answer"] == "4"
    assert page.evaluate("window.sent") == 1 and page.evaluate("window.wrongSend") is False
    assert _guard_state() == "idle"
    restarted = work.WorkWebClient()
    def forbidden_files():
        raise AssertionError("a completed transfer must not reopen original files")
    assert json.loads(_booklet(restarted, tab, forbidden_files)) == first
    assert restarted.conversation_id == "12345678-1234-1234-1234-123456789abc"
    assert page.evaluate("window.sent") == 1
    assert json.loads((tmp_path / "browser-state" / "chats.json").read_text())["chats"]["work:local-fixture"]["transfer"]["pending"] is None


def test_late_work_final_clears_only_own_uncertain_send_on_restart(page):
    _upload_composer(page)
    page.evaluate("window.suppressFinal = true")
    tab = _VenueTab(page)
    with pytest.raises(chatgpt_web.ChatGptWebUncertain):
        _booklet(work.WorkWebClient(), tab, lambda: [_payload()])
    assert _guard_state() == "uncertain"
    page.evaluate("window.finish()")
    assert json.loads(_booklet(work.WorkWebClient(), tab, lambda: []))["questions"]
    assert page.evaluate("window.sent") == 1 and _guard_state() == "idle"


def test_large_booklet_ack_then_plain_user_followup_and_restart_keep_the_same_chat(page, monkeypatch):
    _upload_composer(page)
    monkeypatch.setattr(work.WorkWebClient, "transfer_batch_bytes", 40)
    files = [_payload(f"part{index}.zip", bytes([index]) * 20) for index in range(3)]
    tab = _VenueTab(page)
    result = json.loads(_booklet(work.WorkWebClient(), tab, lambda: iter(files)))
    assert result["questions"] and page.evaluate("window.sent") == 2
    assert page.locator(work.USER_SEL).count() == 2
    assert page.locator(".rich-text-user-turn").count() == 1
    assert page.evaluate("window.uploaded") == [item["name"] for item in files]
    assert json.loads(_booklet(work.WorkWebClient(), tab, lambda: [])) == result
    assert page.evaluate("window.sent") == 2 and _guard_state() == "idle"


def test_listening_uses_only_original_audio_in_the_reading_conversation(page):
    _upload_composer(page)
    tab = _VenueTab(page)
    client = work.WorkWebClient()
    _booklet(client, tab, lambda: [_payload()], booklet_stage="reading")
    audio = chatgpt_web.audio_payload("original.wav", b"RIFF original audio")
    result = json.loads(_booklet(work.WorkWebClient(), tab, lambda: [audio], booklet_stage="listening",
        stage_audio_digest=chatgpt_web._digest(audio["buffer"]), stage_question_ids=["q1"]))
    assert result["questions"][0]["question_id"] == "q1"
    assert page.evaluate("window.uploaded") == ["originals.zip", "original.wav"]
    assert page.evaluate("window.sent") == 2 and page.locator(work.USER_SEL).count() == 2
    assert _guard_state() == "idle"


def test_work_changed_binding_after_attach_stops_before_any_submit(page):
    _upload_composer(page)
    calls = []
    def changed():
        calls.append(True)
        assert page.evaluate("document.getElementById('cards').children.length") == 1
        raise ValueError("generation changed")
    with pytest.raises(chatgpt_web.ChatGptWebBlocked, match="binding"):
        _booklet(work.WorkWebClient(), _VenueTab(page), lambda: [_payload()], before_submit=changed)
    assert calls == [True] and page.evaluate("window.sent") == 0


def test_work_reads_the_visible_idless_composer_even_with_a_hidden_previous_chat(page):
    _upload_composer(page)
    page.evaluate("document.body.insertAdjacentHTML('afterbegin','<div id=prompt-textarea style=display:none contenteditable=true></div>')")
    assert json.loads(_booklet(work.WorkWebClient(), _VenueTab(page), lambda: [_payload()]))["questions"]
    assert page.evaluate("window.sent") == 1


def test_an_unrelated_draft_inserted_while_inspecting_settings_is_never_sent(page):
    _upload_composer(page)
    client = work.WorkWebClient()
    original = client._verify_model
    def verify(page, *, select=False):
        selected = original(page, select=select)
        if not select:
            page.evaluate("document.getElementById('work-composer').append(' unrelated draft')")
        return selected
    client._verify_model = verify
    with pytest.raises(chatgpt_web.ChatGptWebBlocked, match="draft"):
        _booklet(client, _VenueTab(page), lambda: [_payload()])
    assert page.evaluate("window.sent") == 0 and _guard_state() == "idle"


def test_sealed_settings_override_later_environment_changes_before_send(page, monkeypatch):
    from app.solvers import cdp

    _upload_composer(page)
    tab = _VenueTab(page)
    class LocalBrowser:
        contexts = [_Context(tab)]
        def close(self):
            pass
    monkeypatch.setattr(cdp, "connect_over_cdp", lambda endpoint: LocalBrowser())
    monkeypatch.setenv("ROKID_WORK_MODEL", "gpt-6.1-terra")
    client = work.WorkWebClient()
    result = client.complete_json(system="Answer", prompt="All questions", files=lambda: [_payload()],
        chat_key="work:sealed-settings", expect=("questions",), booklet=True,
        requested_settings={"model": "gpt-6.1-sol", "effort": "xhigh", "speed": "fast"})
    assert result["questions"] and page.evaluate("window.sent") == 1
    assert page.evaluate("document.getElementById('sol').getAttribute('aria-checked')") == "true"
    assert client.conversation_id == "12345678-1234-1234-1234-123456789abc"
