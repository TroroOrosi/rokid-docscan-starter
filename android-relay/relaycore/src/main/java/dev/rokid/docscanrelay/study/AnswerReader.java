package dev.rokid.docscanrelay.study;

import java.util.ArrayList;
import java.util.List;

/** Offline navigation; no camera, network, clock or Android lifecycle dependency. */
public final class AnswerReader {
    public enum Screen { ANSWER, GROUPS, QUESTIONS }
    private AnswerBundle bundle;
    private int questionIndex;
    private int anchorOffset;
    private int pageIndex;
    private float width;
    private int lines;
    private AnswerLayout.Measurer measurer;
    private List<AnswerLayout.Page> pages;
    private int textPageCount;
    private int contentLength;
    private Screen screen = Screen.ANSWER;
    private int menuIndex;
    private String menuGroup;
    private final boolean continuous;
    private final List<Integer> pageQuestions = new ArrayList<>();
    private final List<Integer> pageOffsets = new ArrayList<>();
    private final List<AnswerDiagram> pageDiagrams = new ArrayList<>();

    public AnswerReader(AnswerBundle bundle, float width, int lines, AnswerLayout.Measurer measurer) {
        this(bundle, width, lines, measurer, false);
    }

    public AnswerReader(AnswerBundle bundle, float width, int lines, AnswerLayout.Measurer measurer,
                        boolean continuous) {
        this.bundle = bundle;
        this.continuous = continuous;
        viewport(width, lines, measurer);
    }

    public AnswerBundle bundle() { return bundle; }
    public AnswerItem current() { return bundle.items.get(questionIndex); }
    public Screen screen() { return screen; }
    public int offset() { return anchorOffset; }
    public int pageNumber() { return pageIndex + 1; }
    public int pageCount() { return continuous ? pages.size() : textPageCount + current().diagrams.size(); }
    public AnswerLayout.Page page() { return pages.get(Math.min(pageIndex, pages.size()-1)); }
    public AnswerDiagram diagram() {
        if (continuous) return screen == Screen.ANSWER ? pageDiagrams.get(pageIndex) : null;
        return screen == Screen.ANSWER && pageIndex >= textPageCount
                ? current().diagrams.get(pageIndex - textPageCount) : null;
    }

    private int pageStart() {
        if (continuous) return pageOffsets.get(pageIndex);
        return pageIndex < textPageCount ? pages.get(pageIndex).start
                : contentLength + 1 + pageIndex - textPageCount;
    }

    public void viewport(float width, int lines, AnswerLayout.Measurer measurer) {
        this.width = width;
        this.lines = lines;
        this.measurer = measurer;
        reflow();
    }

    private void reflow() {
        if (continuous) { reflowContinuous(); return; }
        AnswerItem item = current();
        String content = content(item);
        pages = AnswerLayout.paginate(content, width, lines, measurer);
        contentLength = content.length();
        textPageCount = content.isEmpty() && !item.diagrams.isEmpty() ? 0 : pages.size();
        pageIndex = 0;
        if (anchorOffset > contentLength && !item.diagrams.isEmpty()) {
            pageIndex = textPageCount + Math.min(item.diagrams.size()-1, anchorOffset-contentLength-1);
        } else {
            while (pageIndex + 1 < textPageCount && pages.get(pageIndex).end <= anchorOffset) pageIndex++;
        }
    }

    private static String content(AnswerItem item) {
        String content;
        switch (item.status) {
            case READY: content = item.answer; break;
            // The warning comes first so the operator knows the answer is
            // incomplete before copying it, and the answer still follows.
            case NEEDS_REVIEW: content = "【要確認】" + item.issue + "\n" + item.answer; break;
            case NEEDS_INPUT: content = "資料不足\n" + item.issue; break;
            case FAILED: content = "解析できません\n" + item.issue; break;
            default: content = "解析中"; break;
        }
        for (int i = 0; i < item.diagrams.size(); i++) content += item.diagrams.get(i).readingText(i + 1);
        return content;
    }

    /** Pack adjacent text answers; figures remain separate pages in their original order. */
    private void reflowContinuous() {
        int targetQuestion = questionIndex;
        int targetOffset = anchorOffset;
        pages = new ArrayList<>();
        pageQuestions.clear(); pageOffsets.clear(); pageDiagrams.clear();
        int first = 0;
        while (first < bundle.items.size()) {
            int last = first;
            while (last + 1 < bundle.items.size() && bundle.items.get(last).diagrams.isEmpty()) last++;
            StringBuilder text = new StringBuilder();
            List<Integer> starts = new ArrayList<>();
            List<Integer> bodyStarts = new ArrayList<>();
            for (int i = first; i <= last; i++) {
                AnswerItem item = bundle.items.get(i);
                starts.add(text.length());
                text.append(item.readingLabel()).append(' ');
                bodyStarts.add(text.length());
                text.append(content(item));
                if (i < last) text.append('\n');
            }
            for (AnswerLayout.Page page : AnswerLayout.paginate(text.toString(), width, lines, measurer)) {
                int owner = 0;
                while (owner + 1 < starts.size() && starts.get(owner + 1) <= page.start) owner++;
                pages.add(page);
                pageQuestions.add(first + owner);
                pageOffsets.add(Math.max(0, page.start - bodyStarts.get(owner)));
                pageDiagrams.add(null);
            }
            AnswerItem item = bundle.items.get(last);
            for (int d = 0; d < item.diagrams.size(); d++) {
                pages.add(AnswerLayout.paginate("", width, lines, measurer).get(0));
                pageQuestions.add(last);
                pageOffsets.add(content(item).length() + 1 + d);
                pageDiagrams.add(item.diagrams.get(d));
            }
            first = last + 1;
        }
        pageIndex = 0;
        for (int p = 0; p < pages.size(); p++) {
            if (pageQuestions.get(p) < targetQuestion || (pageQuestions.get(p) == targetQuestion
                    && pageOffsets.get(p) <= targetOffset)) pageIndex = p;
        }
        questionIndex = targetQuestion;
        anchorOffset = targetOffset;
    }

    private void selectContinuousPage() {
        questionIndex = pageQuestions.get(pageIndex);
        anchorOffset = pageOffsets.get(pageIndex);
    }

    public boolean accept(AnswerBundle next) {
        if (!bundle.sessionId.equals(next.sessionId) || !bundle.inputDigest.equals(next.inputDigest)
                || next.revision <= bundle.revision) return false;
        boolean sameShape = next.items.size() == bundle.items.size();
        for (int i = 0; sameShape && i < bundle.items.size(); i++) {
            AnswerItem old = bundle.items.get(i);
            AnswerItem item = next.items.get(i);
            sameShape = old.questionId.equals(item.questionId) && old.groupId.equals(item.groupId)
                    && old.groupLabel.equals(item.groupLabel) && old.questionLabel.equals(item.questionLabel);
        }
        if (!sameShape) {
            // The same questions never change order or identity. A deck with none
            // of the old question ids is a replacement: the one row a failed
            // message left, replaced by the model's list on a retry.
            for (AnswerItem item : next.items) {
                for (AnswerItem old : bundle.items) {
                    if (old.questionId.equals(item.questionId)) return false;
                }
            }
            bundle = next;
            questionIndex = 0;
            anchorOffset = 0;
            screen = Screen.ANSWER;
            menuIndex = 0;
            menuGroup = null;
            reflow();
            return true;
        }
        boolean changed = !current().answer.equals(next.items.get(questionIndex).answer)
                || current().status != next.items.get(questionIndex).status
                || !current().issue.equals(next.items.get(questionIndex).issue)
                || !current().diagrams.equals(next.items.get(questionIndex).diagrams);
        bundle = next;
        if (changed || continuous) reflow();
        return true;
    }

    public void restore(String questionId, int offset) {
        for (int i = 0; i < bundle.items.size(); i++) {
            if (bundle.items.get(i).questionId.equals(questionId)) {
                questionIndex = i;
                anchorOffset = Math.max(0, offset);
                reflow();
                if (continuous) return;
                anchorOffset = Math.min(anchorOffset, contentLength + current().diagrams.size());
                return;
            }
        }
    }

    public void forward() {
        if (screen != Screen.ANSWER) {
            menuIndex = Math.min(menuIndex + 1, menuChoices().size() - 1);
        } else if (pageIndex + 1 < pageCount()) {
            pageIndex++;
            if (continuous) { selectContinuousPage(); return; }
            anchorOffset = pageStart();
        } else if (!continuous && questionIndex + 1 < bundle.items.size()) {
            questionIndex++;
            anchorOffset = 0;
            reflow();
        }
    }

    public void backward() {
        if (screen != Screen.ANSWER) {
            menuIndex = Math.max(menuIndex - 1, 0);
        } else if (pageIndex > 0) {
            pageIndex--;
            if (continuous) { selectContinuousPage(); return; }
            anchorOffset = pageStart();
        } else if (!continuous && questionIndex > 0) {
            questionIndex--;
            reflow();
            pageIndex = pageCount() - 1;
            anchorOffset = pageStart();
        }
    }

    public void tap() {
        if (screen == Screen.ANSWER) {
            screen = Screen.GROUPS;
            menuIndex = groupIds().indexOf(current().groupId);
        } else if (screen == Screen.GROUPS) {
            menuGroup = groupIds().get(menuIndex);
            screen = Screen.QUESTIONS;
            menuIndex = 0;
            List<Integer> choices = questionIndexes();
            for (int i = 0; i < choices.size(); i++) if (choices.get(i) == questionIndex) menuIndex = i;
        } else {
            questionIndex = questionIndexes().get(menuIndex);
            anchorOffset = 0;
            screen = Screen.ANSWER;
            reflow();
        }
    }

    /** True only when the host should persist CLOSED and leave answer reading. */
    public boolean back() {
        if (screen == Screen.ANSWER) return true;
        if (screen == Screen.QUESTIONS) {
            screen = Screen.GROUPS;
            menuIndex = groupIds().indexOf(menuGroup);
        } else screen = Screen.ANSWER;
        return false;
    }

    public String selectionLabel() { return menuChoices().get(menuIndex); }
    public int selectionNumber() { return menuIndex + 1; }
    public int selectionCount() { return menuChoices().size(); }

    private List<String> groupIds() {
        List<String> ids = new ArrayList<>();
        for (AnswerItem item : bundle.items) if (!ids.contains(item.groupId)) ids.add(item.groupId);
        return ids;
    }

    private List<Integer> questionIndexes() {
        List<Integer> indexes = new ArrayList<>();
        for (int i = 0; i < bundle.items.size(); i++) {
            if (bundle.items.get(i).groupId.equals(menuGroup)) indexes.add(i);
        }
        return indexes;
    }

    private List<String> menuChoices() {
        List<String> choices = new ArrayList<>();
        if (screen == Screen.QUESTIONS) {
            for (int index : questionIndexes()) choices.add(bundle.items.get(index).questionLabel);
        } else {
            for (String id : groupIds()) {
                for (AnswerItem item : bundle.items) {
                    if (item.groupId.equals(id)) { choices.add(item.groupLabel); break; }
                }
            }
        }
        return choices;
    }
}
