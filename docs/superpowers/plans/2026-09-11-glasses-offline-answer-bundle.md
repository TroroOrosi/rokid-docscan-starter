# Glasses offline answer bundle implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the glasses fetch one complete answer bundle over the phone's
hotspot and then read every sub-question's answer offline.

**Architecture:** The server grows one read-only endpoint that emits the exact
JSON `AnswerBundle.fromJson` already parses, deriving the missing 大問/小問
hierarchy from the deck's `question_no` ordering. `DocScanApi` grows one method.
The glasses activity swaps `HudView` for the existing `AnswerView`, persists the
reader cursor through the existing `AnswerStore`, and routes the four measured
gestures onto `AnswerReader`. No device-to-device protocol is added.

**Tech Stack:** FastAPI + SQLite + pytest + ruff on the server; Java 17,
OkHttp 4.12.0, JUnit 4.13.2, Robolectric 4.14.1 and MockWebServer 4.12.0 on
Android.

**Spec:** `docs/superpowers/specs/2026-09-11-glasses-offline-answer-bundle-design.md`

## Global Constraints

- Server checks: `py -3.12 -m pytest -q` and `ruff check .` from the repo root.
- Android checks, from a Bash shell:
  ```bash
  export JAVA_HOME="C:/Users/Public/rokid-build-tools-20260901/jdk17/jdk-17.0.20.1+1"
  export ANDROID_HOME="C:/Users/pupu_/AppData/Local/Android/Sdk"
  /c/rokid-docscan-starter/android-relay/gradlew --no-daemon test testDebugUnitTest assembleDebug
  ```
  Use `gradlew`, not `gradlew.bat`. `test` is not redundant: `:glassinput` is a
  plain `java-library` whose tests only run under `test`.
- Never `git add -A`. `.agents/skills/`, `.claude/`, `.cursor/`, `.specify/` and
  `openspec/` are untracked on purpose. Stage named paths only.
- `AnswerItem.identifier` accepts `[A-Za-z0-9_.-]{1,120}` only. Group and
  question identifiers must be synthesized ASCII; Japanese text belongs in
  `groupLabel`/`questionLabel`, which allow up to 120 characters.
- `AnswerItem` rejects a non-`READY` item whose answer string is non-empty, and
  rejects a `READY` item whose answer is blank.
- An Android build proves compilation only. Do not mark hardware behaviour
  verified in any commit message or document.

## File structure

| File | Responsibility |
|---|---|
| `app/layout.py` | Modify `_PAREN_Q_RE` so `(三)` and `(A)` start a sub-question |
| `tests/test_layout.py` | Segmenter cases for the new markers |
| `app/main.py` | Grouping helper, digest, revision, the new endpoint |
| `app/version.py` | `API_VERSION` bump |
| `README.md` | Version line the documentation contract test asserts |
| `tests/test_answer_bundle_api.py` | New endpoint's tests |
| `android-relay/relaycore/.../DocScanApi.java` | `answerBundle(long)` |
| `android-relay/relaycore/src/test/.../DocScanApiAnswerBundleTest.java` | Parse test |
| `android-relay/glassdoc/.../AnswerGestures.java` | Gesture-to-reader routing |
| `android-relay/glassdoc/src/test/.../AnswerGesturesTest.java` | Routing test |
| `android-relay/glassdoc/.../DocScanGlassActivity.java` | Fetch, persist, swap views |

---

### Task 1: Split `(三)` and `(A)` into their own sub-questions

**Files:**
- Modify: `app/layout.py:32`
- Test: `tests/test_layout.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `layout.segment_problems` returns a `ProblemUnit` whose
  `question_no` is `(三)` or `(A)` for those lines. Task 2 relies on those
  strings reaching `questions.question_no`.

- [ ] **Step 1: Write failing test**

  Append to `tests/test_layout.py`:

  ```python
  def test_kanji_and_letter_sub_questions_split():
      text = "\n".join([
          "第1問 次の問いに答えよ。",
          "(三) 傍線部の理由を述べよ。",
          "(A) 自由英作文を書け。",
          "（Ａ） 全角の英字も設問である。",
      ])
      numbers = [p.question_no for p in layout.segment_problems([(0, text)])]
      assert numbers == ["第1問", "(三)", "(A)", "(Ａ)"]


  def test_mid_text_parentheses_are_not_sub_questions():
      text = "\n".join([
          "第1問 次の問いに答えよ。",
          "第一次大戦（1914）について述べよ。",
          "A) りんご",
      ])
      units = layout.segment_problems([(0, text)])
      assert [p.question_no for p in units] == ["第1問"]
      assert units[0].choices == ["りんご"]
  ```

- [ ] **Step 2: Run the tests and verify they fail**

  Run: `py -3.12 -m pytest tests/test_layout.py -k "kanji_and_letter or mid_text_parentheses" -v`

  Expected: FAIL. The first test reports
  `assert ['第1問'] == ['第1問', '(三)', '(A)', '(Ａ)']` because the
  parenthesized lines are absorbed into the body.

- [ ] **Step 3: Widen the marker**

  Replace `app/layout.py:32`:

  ```python
  _PAREN_Q_RE = re.compile(
      r"^\s*[（(]\s*(?:([0-9０-９]{1,3})|([一二三四五六七八九十]{1,3})|([A-ZＡ-Ｚ]))\s*[)）]"
  )
  ```

  In `_detect_question_no`, replace the `_PAREN_Q_RE` branch so a kanji or
  letter marker keeps its own character and only Arabic digits are normalized:

  ```python
      m = _PAREN_Q_RE.match(line)
      if m:
          digits, kanji, letter = m.group(1), m.group(2), m.group(3)
          if digits is not None:
              return f"({_zen_to_han(digits)})"
          return f"({kanji or letter})"
  ```

  Leave `_CHOICE_RE` alone. It matches `A.`/`A)`/`A、` without a leading
  parenthesis, so it does not compete with `(A)`, and the classification loop at
  `app/layout.py:120` prefers a choice over a question number when both match.

- [ ] **Step 4: Run the tests and verify they pass**

  Run: `py -3.12 -m pytest tests/test_layout.py -v`

  Expected: PASS, including the pre-existing cases.

- [ ] **Step 5: Run the whole server suite**

  Run: `py -3.12 -m pytest -q` then `ruff check .`

  Expected: no failures; `All checks passed!`. Segmentation feeds many tests, so
  a regression here shows up outside `tests/test_layout.py`.

- [ ] **Step 6: Commit**

  ```bash
  git add app/layout.py tests/test_layout.py
  git commit -m "fix: split kanji and letter sub-questions"
  ```

---

### Task 2: Serve the answer bundle

**Files:**
- Modify: `app/main.py` (helpers next to `_exam_deck`, endpoint next to
  `GET /v1/exam-sessions/{session_id}/solutions` at `app/main.py:2695`)
- Modify: `app/version.py:167`
- Modify: `README.md`
- Test: `tests/test_answer_bundle_api.py`

**Interfaces:**
- Consumes: Task 1's `question_no` strings.
- Produces: `GET /v1/exam-sessions/{session_id}/answer-bundle` returning
  `{"schema_version": 1, "session_id": str, "input_digest": str,
  "revision": int, "items": [{"group_id", "group_label", "question_id",
  "question_label", "answer", "status", "issue"}]}`. Task 3 parses it.

- [ ] **Step 1: Write failing tests**

  Create `tests/test_answer_bundle_api.py`:

  ```python
  """The offline answer bundle the glasses read (see
  docs/superpowers/specs/2026-09-11-glasses-offline-answer-bundle-design.md)."""

  import importlib

  import pytest
  from fastapi.testclient import TestClient


  @pytest.fixture
  def client(tmp_path, monkeypatch):
      monkeypatch.setenv("ROKID_DATA_DIR", str(tmp_path))
      monkeypatch.delenv("ROKID_ALLOW_REAL_EXAM_SOLVE", raising=False)
      import app.config as config
      importlib.reload(config)
      import app.db as db
      importlib.reload(db)
      import app.main as main
      importlib.reload(main)
      return TestClient(main.app)


  def _session_with(client, pages):
      doc_id = client.post("/v1/documents", json={"title": "t"}).json()["document_id"]
      for index, text in enumerate(pages):
          client.post(
              f"/v1/documents/{doc_id}/pages",
              data={"page_index": index, "ocr_text": text},
          )
      client.post(f"/v1/documents/{doc_id}/finalize")
      session_id = client.post(
          "/v1/exam-sessions",
          json={
              "mode": "study",
              "document_id": doc_id,
              "exam_type": "written",
              "answer_format": "mark",
          },
      ).json()["session_id"]
      return doc_id, session_id


  PAGE = "\n".join([
      "第1問 次の問いに答えよ。",
      "問1 2x + 3 = 7 を解け。",
      "問2 その理由を述べよ。",
      "第2問 図を見て答えよ。",
  ])


  def test_bundle_groups_sub_questions_under_their_section(client):
      _, session_id = _session_with(client, [PAGE])
      client.post(f"/v1/exam-sessions/{session_id}/finalize-reading")

      body = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle").json()

      assert body["schema_version"] == 1
      assert body["session_id"] == str(session_id)
      assert len(body["input_digest"]) == 64
      assert body["revision"] >= 1
      assert [(i["group_label"], i["question_label"]) for i in body["items"]] == [
          ("第1問", "問1"),
          ("第1問", "問2"),
          ("第2問", "全問"),
      ]
      assert body["items"][0]["group_id"] == "g1"
      assert body["items"][2]["group_id"] == "g2"
      assert all(i["question_id"].startswith("q") for i in body["items"])


  def test_unsolved_items_are_pending_with_no_answer_text(client):
      _, session_id = _session_with(client, [PAGE])
      client.post(f"/v1/exam-sessions/{session_id}/finalize-reading")

      items = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle").json()["items"]

      for item in items:
          if item["status"] != "ready":
              assert item["answer"] == ""
              assert item["issue"]


  def test_a_section_without_sub_questions_becomes_one_whole_item(client):
      # tests/fixtures/answer_forms/cases.json stores each page as a single
      # line, so the segmenter yields the 第N問 heading alone. The group must
      # still carry one item, or AnswerBundle rejects the whole snapshot.
      _, session_id = _session_with(
          client, ["第1問 問1 頂点の y 座標を求めよ。 問2 最小値を答えよ。"]
      )
      client.post(f"/v1/exam-sessions/{session_id}/finalize-reading")

      items = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle").json()["items"]

      assert [(i["group_label"], i["question_label"]) for i in items] == [
          ("第1問", "全問"),
      ]


  def test_digest_is_stable_and_revision_never_goes_backwards(client):
      _, session_id = _session_with(client, [PAGE])
      client.post(f"/v1/exam-sessions/{session_id}/finalize-reading")
      first = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle").json()
      second = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle").json()

      assert first["input_digest"] == second["input_digest"]
      assert second["revision"] >= first["revision"]


  def test_reading_phase_is_409(client):
      _, session_id = _session_with(client, [PAGE])

      response = client.get(f"/v1/exam-sessions/{session_id}/answer-bundle")

      assert response.status_code == 409
      assert "finalize-reading" in response.json()["detail"]


  def test_unknown_session_is_404(client):
      assert client.get("/v1/exam-sessions/9999/answer-bundle").status_code == 404
  ```

- [ ] **Step 2: Run the tests and verify they fail**

  Run: `py -3.12 -m pytest tests/test_answer_bundle_api.py -v`

  Expected: FAIL with 404 responses, because the route does not exist yet.

- [ ] **Step 3: Add the helpers**

  In `app/main.py`, beside `_exam_deck`:

  ```python
  # 大問 headings, as the segmenter emits them (app/layout.py:64).
  _GROUP_NO_RE = re.compile(r"^(?:大問\s*[0-9０-９]+|第\s*[0-9０-９]+\s*問)")


  def _answer_groups(conn, session_id: int) -> list[dict]:
      """Deck rows folded into 大問 groups, in document order.

      A heading row is the group's label, not an answer. A group that collects
      no sub-question keeps its own heading row as one 全問 item, which is the
      figure-style whole-section form (T02/T04 in the answer-form pack) and also
      what stops AnswerBundle from rejecting an empty group.
      """
      groups: list[dict] = []
      for row in _deck_question_rows(conn, session_id):
          label = row["question_no"] or "全問"
          if _GROUP_NO_RE.match(label):
              groups.append({"id": f"g{len(groups) + 1}", "label": label,
                             "heading": row, "items": [], "whole": False})
              continue
          if not groups:
              groups.append({"id": "g1", "label": "全体",
                             "heading": row, "items": [], "whole": False})
          groups[-1]["items"].append(row)
      for group in groups:
          if not group["items"]:
              group["items"] = [group["heading"]]
              group["whole"] = True
      return groups


  def _answer_bundle_item(conn, group: dict, row) -> dict:
      sol = _latest_solution_row(conn, row["id"])
      answer = (sol["answer"] or "").strip() if sol is not None else ""
      if sol is None:
          status, issue = "pending", "未解答"
      elif answer:
          status, issue = "ready", ""
      else:
          status, issue = "failed", "解答本文がありません"
      label = "全問" if group["whole"] else (row["question_no"] or "全問")
      return {
          "group_id": group["id"],
          "group_label": group["label"][:120],
          "question_id": f"q{row['id']}",
          "question_label": label[:120],
          "answer": answer if status == "ready" else "",
          "status": status,
          "issue": issue,
      }


  def _answer_input_digest(conn, session) -> str:
      """Input identity: the pages the answers were read from.

      Stable while the material is unchanged, different after a re-capture, so
      AnswerStore can refuse a bundle belonging to different input.
      """
      document_id = session["document_id"]
      if document_id:
          rows = conn.execute(
              "SELECT page_index, phash, ocr_md5 FROM pages "
              "WHERE document_id = ? ORDER BY page_index",
              (document_id,),
          ).fetchall()
          material = "\n".join(
              f"{r['page_index']}:{r['phash']}:{r['ocr_md5'] or ''}" for r in rows
          )
      else:
          material = "\n".join(
              str(r["id"]) for r in _deck_question_rows(conn, session["id"])
          )
      return hashlib.sha256(material.encode("utf-8")).hexdigest()


  def _answer_revision(conn, session_id: int) -> int:
      """Monotonic snapshot number; AnswerStore rejects anything older."""
      row = conn.execute(
          "SELECT MAX(s.id) AS latest FROM solutions s "
          "JOIN questions q ON q.id = s.question_id WHERE q.session_id = ?",
          (session_id,),
      ).fetchone()
      return (row["latest"] or 0) + 1
  ```

  `hashlib` and `re` are already imported in `app/main.py`.

- [ ] **Step 4: Add the endpoint**

  In `app/main.py`, after `exam_list_solutions`:

  ```python
  @app.get("/v1/exam-sessions/{session_id}/answer-bundle")
  def exam_answer_bundle(session_id: int) -> dict:
      """One complete snapshot the glasses read offline.

      The schema is AnswerBundle's, parsed by
      android-relay/relaycore/.../study/AnswerBundle.java. It has no way to say
      "locked" or "still reading", so those are 409s rather than a partial body.
      """
      conn = db.connect()
      try:
          session = _exam_session_or_404(conn, session_id)
          if _session_phase(session) == "reading":
              raise HTTPException(status_code=409, detail="call finalize-reading first")
          if session["mode"] == "real" and not config.ALLOW_REAL_EXAM_SOLVE:
              raise HTTPException(status_code=409, detail="real-mode answers are locked")
          groups = _answer_groups(conn, session_id)
          if not groups:
              raise HTTPException(
                  status_code=409,
                  detail="no problems were detected in this document",
              )
          items = [
              _answer_bundle_item(conn, group, row)
              for group in groups
              for row in group["items"]
          ]
          return {
              "schema_version": 1,
              "session_id": str(session_id),
              "input_digest": _answer_input_digest(conn, session),
              "revision": _answer_revision(conn, session_id),
              "items": items,
          }
      finally:
          conn.close()
  ```

- [ ] **Step 5: Run the tests and verify they pass**

  Run: `py -3.12 -m pytest tests/test_answer_bundle_api.py -v`

  Expected: PASS, all six.

- [ ] **Step 6: Bump the API version**

  In `app/version.py:167` set `API_VERSION = "1.16.0"`, and add a line to the
  changelog comment block above it in the file's existing style, naming the new
  endpoint.

  Update the version line in `README.md` so it reads
  `Server APP 0.17.0 / API 1.16.0 / Android client <unchanged> / Glasses View <unchanged>`,
  copying the surrounding format exactly. `tests/test_documentation_contract.py`
  builds that string from `app/version.py` and
  `android-relay/app/build.gradle.kts`, so read those two files for the values
  rather than typing them from memory.

- [ ] **Step 7: Run the whole server suite**

  Run: `py -3.12 -m pytest -q` then `ruff check .`

  Expected: no failures; `All checks passed!`.

- [ ] **Step 8: Commit**

  ```bash
  git add app/main.py app/version.py README.md tests/test_answer_bundle_api.py
  git commit -m "feat: serve a complete answer bundle for offline reading"
  ```

---

### Task 3: Fetch the bundle from the relay client

**Files:**
- Modify: `android-relay/relaycore/src/main/java/dev/rokid/docscanrelay/DocScanApi.java`
- Test: `android-relay/relaycore/src/test/java/dev/rokid/docscanrelay/DocScanApiAnswerBundleTest.java`

**Interfaces:**
- Consumes: Task 2's endpoint.
- Produces: `public AnswerBundle answerBundle(long sessionId) throws IOException,
  JSONException`. Task 4 calls it.

- [ ] **Step 1: Write a failing test**

  Create `DocScanApiAnswerBundleTest.java`:

  ```java
  package dev.rokid.docscanrelay;

  import static org.junit.Assert.assertEquals;
  import static org.junit.Assert.assertThrows;

  import dev.rokid.docscanrelay.study.AnswerBundle;
  import dev.rokid.docscanrelay.study.AnswerItem;
  import java.io.IOException;
  import okhttp3.mockwebserver.MockResponse;
  import okhttp3.mockwebserver.MockWebServer;
  import okhttp3.mockwebserver.RecordedRequest;
  import org.junit.Test;

  public class DocScanApiAnswerBundleTest {
      private static final String BODY = "{\"schema_version\":1,"
              + "\"session_id\":\"7\",\"input_digest\":\"" + "a".repeat(64) + "\","
              + "\"revision\":3,\"items\":[{\"group_id\":\"g1\",\"group_label\":\"第1問\","
              + "\"question_id\":\"q10\",\"question_label\":\"問1\",\"answer\":\"x = 2\","
              + "\"status\":\"ready\",\"issue\":\"\"},{\"group_id\":\"g1\","
              + "\"group_label\":\"第1問\",\"question_id\":\"q11\",\"question_label\":\"問2\","
              + "\"answer\":\"\",\"status\":\"pending\",\"issue\":\"未解答\"}]}";

      private DocScanApi api(MockWebServer server) {
          return new DocScanApi(
                  server.url("/").toString().replaceAll("/$", ""),
                  "",
                  new ClientIdentity("test", "test/1", "test"));
      }

      @Test
      public void parsesTheBundleAndAsksTheRightPath() throws Exception {
          try (MockWebServer server = new MockWebServer()) {
              server.enqueue(new MockResponse().setBody(BODY));

              AnswerBundle bundle = api(server).answerBundle(7);

              RecordedRequest request = server.takeRequest();
              assertEquals("/v1/exam-sessions/7/answer-bundle", request.getPath());
              assertEquals("GET", request.getMethod());
              assertEquals("7", bundle.sessionId);
              assertEquals(3, bundle.revision);
              assertEquals(2, bundle.items.size());
              assertEquals("x = 2", bundle.items.get(0).answer);
              assertEquals(AnswerItem.Status.PENDING, bundle.items.get(1).status);
          }
      }

      @Test
      public void surfacesTheServerRefusal() throws Exception {
          try (MockWebServer server = new MockWebServer()) {
              server.enqueue(new MockResponse().setResponseCode(409)
                      .setBody("{\"detail\":\"call finalize-reading first\"}"));

              DocScanApi.ApiException error = assertThrows(
                      DocScanApi.ApiException.class, () -> api(server).answerBundle(7));

              assertEquals(409, error.getStatusCode());
              assertEquals("call finalize-reading first", error.getMessage());
          }
      }
  }
  ```

  If `ApiException.getMessage()` does not return the detail, read
  `DocScanApi.java:175` and assert on whatever accessor it does expose rather
  than changing the exception.

- [ ] **Step 2: Run the test and verify it fails**

  ```bash
  export JAVA_HOME="C:/Users/Public/rokid-build-tools-20260901/jdk17/jdk-17.0.20.1+1"
  export ANDROID_HOME="C:/Users/pupu_/AppData/Local/Android/Sdk"
  /c/rokid-docscan-starter/android-relay/gradlew --no-daemon :relaycore:testDebugUnitTest \
      --tests '*DocScanApiAnswerBundleTest*'
  ```

  Expected: compilation failure — `cannot find symbol: method answerBundle(long)`.

- [ ] **Step 3: Add the method**

  In `DocScanApi.java`, after `review(...)`:

  ```java
      /** One complete snapshot, so a reader works with no route to the server. */
      public AnswerBundle answerBundle(long sessionId) throws IOException, JSONException {
          return AnswerBundle.fromJson(
                  get("/v1/exam-sessions/" + sessionId + "/answer-bundle").toString());
      }
  ```

  Add `import dev.rokid.docscanrelay.study.AnswerBundle;` beside the existing
  imports.

- [ ] **Step 4: Run the test and verify it passes**

  Same command as Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add android-relay/relaycore/src/main/java/dev/rokid/docscanrelay/DocScanApi.java \
          android-relay/relaycore/src/test/java/dev/rokid/docscanrelay/DocScanApiAnswerBundleTest.java
  git commit -m "feat: fetch the answer bundle from the relay client"
  ```

---

### Task 4: Route the four gestures onto the reader

**Files:**
- Create: `android-relay/glassdoc/src/main/java/dev/rokid/docscanglass/doc/AnswerGestures.java`
- Test: `android-relay/glassdoc/src/test/java/dev/rokid/docscanglass/doc/AnswerGesturesTest.java`

**Interfaces:**
- Consumes: `AnswerReader` from `:relaycore` and `GlassesInputAction` from
  `:glassinput`.
- Produces: `static boolean AnswerGestures.apply(AnswerReader reader,
  GlassesInputAction action)` returning true while the reader keeps the screen
  and false when the operator has left it. Task 5 calls it.

This mirrors the existing `CaptureActionRouter`: the decision is a pure function
so it can be tested without an Activity.

- [ ] **Step 1: Write a failing test**

  Create `AnswerGesturesTest.java`:

  ```java
  package dev.rokid.docscanglass.doc;

  import static org.junit.Assert.assertEquals;
  import static org.junit.Assert.assertFalse;
  import static org.junit.Assert.assertTrue;

  import dev.rokid.docscanglass.input.GlassesInputAction;
  import dev.rokid.docscanrelay.study.AnswerBundle;
  import dev.rokid.docscanrelay.study.AnswerItem;
  import dev.rokid.docscanrelay.study.AnswerReader;
  import java.util.List;
  import org.junit.Test;

  public class AnswerGesturesTest {
      private AnswerReader reader() {
          AnswerBundle bundle = new AnswerBundle("7", "a".repeat(64), 1, List.of(
                  AnswerItem.ready("g1", "第1問", "q10", "問1", "x = 2"),
                  AnswerItem.ready("g1", "第1問", "q11", "問2", "y = 3")));
          return new AnswerReader(bundle, 400f, 2, text -> text.length() * 10f);
      }

      @Test
      public void forwardAndBackMoveTheReader() {
          AnswerReader reader = reader();

          assertTrue(AnswerGestures.apply(reader, GlassesInputAction.SWIPE_FORWARD));
          assertTrue(AnswerGestures.apply(reader, GlassesInputAction.SWIPE_BACK));

          assertEquals(1, reader.pageNumber());
      }

      @Test
      public void tapOpensTheMenu() {
          AnswerReader reader = reader();

          assertTrue(AnswerGestures.apply(reader, GlassesInputAction.SHORT_TAP));

          assertEquals(AnswerReader.Screen.GROUPS, reader.screen());
      }

      @Test
      public void backLeavesTheReaderOnlyFromTheTop() {
          AnswerReader reader = reader();
          AnswerGestures.apply(reader, GlassesInputAction.SHORT_TAP);

          assertTrue(AnswerGestures.apply(reader, GlassesInputAction.BACK));
          assertFalse(AnswerGestures.apply(reader, GlassesInputAction.BACK));
      }

      @Test
      public void longPressIsNotBound() {
          AnswerReader reader = reader();

          assertTrue(AnswerGestures.apply(reader, GlassesInputAction.LONG_PRESS));

          assertEquals(AnswerReader.Screen.ANSWER, reader.screen());
      }
  }
  ```

  `AnswerReaderTest.java` in `:relaycore` already fixes what `tap()` and
  `back()` do. Read it first, and if `tap()` from the ANSWER screen does not
  reach `GROUPS`, correct this test to match the reader rather than changing the
  reader.

- [ ] **Step 2: Run the test and verify it fails**

  ```bash
  /c/rokid-docscan-starter/android-relay/gradlew --no-daemon :glassdoc:testDebugUnitTest \
      --tests '*AnswerGesturesTest*'
  ```

  Expected: compilation failure — `cannot find symbol: class AnswerGestures`.

- [ ] **Step 3: Write the router**

  ```java
  package dev.rokid.docscanglass.doc;

  import dev.rokid.docscanglass.input.GlassesInputAction;
  import dev.rokid.docscanrelay.study.AnswerReader;

  /**
   * The four gestures the firmware delivers, mapped onto the reader's own verbs.
   *
   * <p>Pure on purpose: the Activity owns the display and the persistence, this
   * owns the decision, and the decision is the part worth testing.</p>
   */
  final class AnswerGestures {
      private AnswerGestures() {
      }

      /** @return true while the reader keeps the screen, false once it is left. */
      static boolean apply(AnswerReader reader, GlassesInputAction action) {
          switch (action) {
              case SWIPE_FORWARD:
                  reader.forward();
                  return true;
              case SWIPE_BACK:
                  reader.backward();
                  return true;
              case SHORT_TAP:
                  reader.tap();
                  return true;
              case BACK:
                  return reader.back();
              default:
                  return true;
          }
      }
  }
  ```

- [ ] **Step 4: Run the test and verify it passes**

  Same command as Step 2. Expected: PASS, four tests.

- [ ] **Step 5: Commit**

  ```bash
  git add android-relay/glassdoc/src/main/java/dev/rokid/docscanglass/doc/AnswerGestures.java \
          android-relay/glassdoc/src/test/java/dev/rokid/docscanglass/doc/AnswerGesturesTest.java
  git commit -m "feat: map the glasses gestures onto the answer reader"
  ```

---

### Task 5: Read the answers on the glasses

**Files:**
- Modify: `android-relay/glassdoc/src/main/java/dev/rokid/docscanglass/doc/DocScanGlassActivity.java`
- Modify: `android-relay/relaycore/src/main/java/dev/rokid/docscanrelay/DocScanController.java`
  (expose the session id)
- Test: `android-relay/glassdoc/src/test/java/dev/rokid/docscanglass/doc/AnswerSurfaceTest.java`

**Interfaces:**
- Consumes: `DocScanApi.answerBundle(long)` (Task 3), `AnswerGestures.apply`
  (Task 4), and the existing `AnswerView`, `AnswerReader`, `AnswerStore`.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Expose the session and the configured client**

  `DocScanController.java:107` holds `private DocScanApi api;` and
  `DocScanController.java:137` holds `private long sessionId;`. The Activity
  needs both, and must not build a second `DocScanApi`, which would carry
  neither the configured base URL nor the key. Make both fields `volatile`,
  matching how `state` is declared at `DocScanController.java:103`, because the
  Activity reads them from its own thread, and add:

  ```java
      /** The finalized exam session, or 0 before one exists. */
      public long sessionId() {
          return sessionId;
      }

      /** The configured client, so a caller never builds an unconfigured one. */
      public DocScanApi api() {
          return api;
      }
  ```

- [ ] **Step 2: Write a failing test**

  Create `AnswerSurfaceTest.java`. It covers the part that is decidable without
  hardware: a fetched bundle is persisted and a later resume restores the same
  place.

  ```java
  package dev.rokid.docscanglass.doc;

  import static org.junit.Assert.assertEquals;
  import static org.junit.Assert.assertNotNull;

  import androidx.test.core.app.ApplicationProvider;
  import dev.rokid.docscanrelay.study.AnswerBundle;
  import dev.rokid.docscanrelay.study.AnswerItem;
  import dev.rokid.docscanrelay.study.AnswerStore;
  import java.io.File;
  import java.util.List;
  import org.junit.Test;
  import org.junit.runner.RunWith;
  import org.robolectric.RobolectricTestRunner;

  @RunWith(RobolectricTestRunner.class)
  public class AnswerSurfaceTest {
      private AnswerBundle bundle() {
          return new AnswerBundle("7", "a".repeat(64), 1, List.of(
                  AnswerItem.ready("g1", "第1問", "q10", "問1", "x = 2"),
                  AnswerItem.ready("g1", "第1問", "q11", "問2", "y = 3")));
      }

      @Test
      public void aFetchedBundleSurvivesAndResumesWhereItWasLeft() throws Exception {
          File directory = ApplicationProvider.getApplicationContext().getFilesDir();
          AnswerStore store = new AnswerStore(directory);

          store.start(bundle());
          store.save(bundle(), "q11", 40, false);
          AnswerStore.Saved resumed = new AnswerStore(directory).resume();

          assertNotNull(resumed);
          assertEquals("q11", resumed.questionId);
          assertEquals(40, resumed.offset);
          assertEquals("7", resumed.bundle.sessionId);
      }
  }
  ```

  Read `AnswerStoreTest.java` in `:relaycore` first and match its calling
  convention; `resume()` may clear a closed flag, and this test must not assert
  the opposite of what that test already fixes.

- [ ] **Step 3: Run the test and verify it fails or passes for the right reason**

  ```bash
  /c/rokid-docscan-starter/android-relay/gradlew --no-daemon :glassdoc:testDebugUnitTest \
      --tests '*AnswerSurfaceTest*'
  ```

  If it passes immediately, that is correct: `AnswerStore` is already
  implemented and tested, and this test only pins the glasses-side directory
  choice. Keep it.

- [ ] **Step 4: Wire the Activity**

  In `DocScanGlassActivity.java`:

  Add fields beside `hud`:

  ```java
      private AnswerView answers;
      private AnswerStore answerStore;
      private AnswerReader reader;
      private volatile boolean fetchingAnswers;
  ```

  In `onCreate`, after `setContentView(hud)`:

  ```java
          answerStore = new AnswerStore(getFilesDir());
  ```

  In `onUpdate`, before the existing state filter, ask for the bundle once the
  session has answers to give:

  ```java
          if (state == RelayState.REVIEW && reader == null && !fetchingAnswers) {
              fetchAnswers(controller.sessionId());
          }
  ```

  Add the fetch. It runs off the main thread because OkHttp refuses to run on
  it, and it never throws into the UI:

  ```java
      /**
       * One request, then the reader works with no route to the server. The exam
       * venue has no Wi-Fi network; the glasses reach the server only while the
       * phone's hotspot is up, which may be true only before the exam starts.
       */
      private void fetchAnswers(long sessionId) {
          if (sessionId <= 0) {
              return;
          }
          fetchingAnswers = true;
          new Thread(() -> {
              try {
                  AnswerBundle bundle = controller.api().answerBundle(sessionId);
                  answerStore.start(bundle);
                  main.post(() -> openAnswers(bundle));
              } catch (Exception error) {
                  Log.w(TAG, "answer bundle unavailable", error);
                  main.post(() -> hud.showLines(
                          List.of("答案を取得できません", "通信を確認", "")));
              } finally {
                  fetchingAnswers = false;
              }
          }, "answer-bundle").start();
      }

      private void openAnswers(AnswerBundle bundle) {
          answers = new AnswerView(this);
          // A placeholder viewport: AnswerView.onSizeChanged calls
          // reader.viewport with its own Paint as soon as it is laid out, and
          // the view owns the layout, so nothing here should guess at width.
          reader = new AnswerReader(bundle, 1f, 2, text -> text.length());
          answers.bind(reader);
          setContentView(answers);
      }

      private void closeAnswers() {
          reader = null;
          answers = null;
          setContentView(hud);
      }
  ```

  In `onAction`, send gestures to the reader while it owns the screen:

  ```java
      private void onAction(GlassesInputAction action) {
          if (action != GlassesInputAction.BACK) {
              backExit.reset();
          }
          if (reader != null) {
              if (!AnswerGestures.apply(reader, action)) {
                  closeAnswers();
                  return;
              }
              answers.refresh();
              return;
          }
          controller.onGlassesAction(action);
      }
  ```

  `AnswerView.refresh()` is already package-private and documented as
  "Re-reads the reader after the host moved it", which is exactly this call. Do
  not add a second redraw method.

- [ ] **Step 5: Build and run the module's tests**

  ```bash
  /c/rokid-docscan-starter/android-relay/gradlew --no-daemon test testDebugUnitTest assembleDebug
  ```

  Expected: `BUILD SUCCESSFUL`, no failures.

- [ ] **Step 6: Commit**

  ```bash
  git add android-relay/glassdoc/src/main/java/dev/rokid/docscanglass/doc/DocScanGlassActivity.java \
          android-relay/relaycore/src/main/java/dev/rokid/docscanrelay/DocScanController.java \
          android-relay/relaycore/src/main/java/dev/rokid/docscanrelay/DocScanApi.java \
          android-relay/glassdoc/src/main/java/dev/rokid/docscanglass/doc/AnswerView.java \
          android-relay/glassdoc/src/test/java/dev/rokid/docscanglass/doc/AnswerSurfaceTest.java
  git commit -m "feat: read the answer bundle on the glasses"
  ```

---

### Task 6: Record what is built and what is still unmeasured

**Files:**
- Modify: `.agents/progress/glasses-input-and-real-device-prep.md`
- Modify: `tasks/todo.md`

**Interfaces:** none.

- [ ] **Step 1: Run every check**

  ```bash
  py -3.12 -m pytest -q
  ruff check .
  export JAVA_HOME="C:/Users/Public/rokid-build-tools-20260901/jdk17/jdk-17.0.20.1+1"
  export ANDROID_HOME="C:/Users/pupu_/AppData/Local/Android/Sdk"
  /c/rokid-docscan-starter/android-relay/gradlew --no-daemon test testDebugUnitTest assembleDebug
  ```

  Record the actual counts. Do not write a number you did not read from output.

- [ ] **Step 2: Append a section to the progress record**

  State, with the commands and their output: what the endpoint returns, that the
  Android side parses it, and that the gesture routing is unit-tested. State
  separately that nothing here is hardware-verified — the hotspot topology, the
  readability of `AnswerView` on the glasses, and reading with the hotspot off
  are all unmeasured. Fix the stale logcat tags in the resume section while you
  are there: the tags are `DocScanGlassDoc` and `WearWatch`, not `DocScanGlass`.

- [ ] **Step 3: Update the task list**

  In `tasks/todo.md`, note under FS-65 that the transport and the reading
  surface are implemented and that the todo-list FS-65 scope — 数式・表・作図 —
  is untouched. Leave the checkbox unchecked; it is not verified.

- [ ] **Step 4: Commit**

  ```bash
  git add .agents/progress/glasses-input-and-real-device-prep.md tasks/todo.md
  git commit -m "docs: record the offline answer path and what it does not prove"
  ```

## Hardware verification (not part of this plan)

Run after Task 6, with the operator wearing the glasses:

1. Start the phone hotspot, join the glasses to it, and confirm `/health`.
2. Fetch one bundle, then turn the hotspot off and read the whole deck.
3. Confirm the three-line `AnswerView` is legible, and record the smallest
   readable text size.
4. Watch with `adb logcat -s DocScanGlassDoc WearWatch`.

Record firmware and app versions with the result, per `CLAUDE.md`.
