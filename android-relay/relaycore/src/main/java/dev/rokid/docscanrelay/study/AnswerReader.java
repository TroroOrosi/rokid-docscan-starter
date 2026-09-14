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
    private Screen screen = Screen.ANSWER;
    private int menuIndex;
    private String menuGroup;

    public AnswerReader(AnswerBundle bundle, float width, int lines, AnswerLayout.Measurer measurer) {
        this.bundle = bundle;
        viewport(width, lines, measurer);
    }

    public AnswerBundle bundle() { return bundle; }
    public AnswerItem current() { return bundle.items.get(questionIndex); }
    public Screen screen() { return screen; }
    public int offset() { return anchorOffset; }
    public int pageNumber() { return pageIndex + 1; }
    public int pageCount() { return pages.size(); }
    public AnswerLayout.Page page() { return pages.get(pageIndex); }

    public void viewport(float width, int lines, AnswerLayout.Measurer measurer) {
        this.width = width;
        this.lines = lines;
        this.measurer = measurer;
        reflow();
    }

    private void reflow() {
        AnswerItem item = current();
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
        pages = AnswerLayout.paginate(content, width, lines, measurer);
        pageIndex = 0;
        while (pageIndex + 1 < pages.size() && pages.get(pageIndex).end <= anchorOffset) pageIndex++;
    }

    public boolean accept(AnswerBundle next) {
        if (!bundle.sessionId.equals(next.sessionId) || !bundle.inputDigest.equals(next.inputDigest)
                || next.revision <= bundle.revision || next.items.size() != bundle.items.size()) return false;
        for (int i = 0; i < bundle.items.size(); i++) {
            AnswerItem old = bundle.items.get(i);
            AnswerItem item = next.items.get(i);
            if (!old.questionId.equals(item.questionId) || !old.groupId.equals(item.groupId)
                    || !old.groupLabel.equals(item.groupLabel) || !old.questionLabel.equals(item.questionLabel)) {
                return false;
            }
        }
        boolean changed = !current().answer.equals(next.items.get(questionIndex).answer)
                || current().status != next.items.get(questionIndex).status
                || !current().issue.equals(next.items.get(questionIndex).issue);
        bundle = next;
        if (changed) reflow();
        return true;
    }

    public void restore(String questionId, int offset) {
        for (int i = 0; i < bundle.items.size(); i++) {
            if (bundle.items.get(i).questionId.equals(questionId)) {
                questionIndex = i;
                anchorOffset = Math.max(0, Math.min(offset, current().answer.length()));
                reflow();
                return;
            }
        }
    }

    public void forward() {
        if (screen != Screen.ANSWER) {
            menuIndex = Math.min(menuIndex + 1, menuChoices().size() - 1);
        } else if (pageIndex + 1 < pages.size()) {
            anchorOffset = pages.get(++pageIndex).start;
        } else if (questionIndex + 1 < bundle.items.size()) {
            questionIndex++;
            anchorOffset = 0;
            reflow();
        }
    }

    public void backward() {
        if (screen != Screen.ANSWER) {
            menuIndex = Math.max(menuIndex - 1, 0);
        } else if (pageIndex > 0) {
            anchorOffset = pages.get(--pageIndex).start;
        } else if (questionIndex > 0) {
            questionIndex--;
            reflow();
            pageIndex = pages.size() - 1;
            anchorOffset = page().start;
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
