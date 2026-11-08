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
    private final List<ContinuousSection> sections = new ArrayList<>();
    private int continuousPageCount;

    public AnswerReader(AnswerBundle bundle, float width, int lines, AnswerLayout.Measurer measurer) {
        this(bundle, width, lines, measurer, false);
    }

    public AnswerReader(AnswerBundle bundle, float width, int lines, AnswerLayout.Measurer measurer,
                        boolean continuous) {
        this(bundle, continuous);
        viewport(width, lines, measurer);
    }

    /** Metadata and cursor are usable before a view supplies its actual font and size. */
    public AnswerReader(AnswerBundle bundle, boolean continuous) {
        this.bundle = bundle;
        this.continuous = continuous;
    }

    public AnswerBundle bundle() { return bundle; }
    public boolean hasViewport() { return measurer != null; }
    public AnswerItem current() { return bundle.items.get(questionIndex); }
    public Screen screen() { return screen; }
    public int offset() { return anchorOffset; }
    public int pageNumber() { return pageIndex + 1; }
    public int pageCount() {
        if (!hasViewport()) throw new IllegalStateException("answer viewport unavailable");
        return continuous ? continuousPageCount : textPageCount + current().diagrams.size();
    }
    public AnswerLayout.Page page() {
        if (!hasViewport()) throw new IllegalStateException("answer viewport unavailable");
        if (!continuous) return pages.get(Math.min(pageIndex, pages.size() - 1));
        ContinuousSection section = sectionAt(pageIndex);
        int localPage = pageIndex - section.firstPage;
        return localPage < section.pages.size() ? section.pages.get(localPage)
                : AnswerLayout.paginate("", width, lines, measurer).get(0);
    }
    public AnswerDiagram diagram() {
        if (!hasViewport()) return null;
        if (continuous) {
            ContinuousSection section = sectionAt(pageIndex);
            int index = pageIndex - section.firstPage - section.pages.size();
            return screen == Screen.ANSWER && index >= 0 ? section.diagrams.get(index) : null;
        }
        return screen == Screen.ANSWER && pageIndex >= textPageCount
                ? current().diagrams.get(pageIndex - textPageCount) : null;
    }

    private int pageStart() {
        if (continuous) return sectionAt(pageIndex).offset(pageIndex);
        return pageIndex < textPageCount ? pages.get(pageIndex).start
                : contentLength + 1 + pageIndex - textPageCount;
    }

    public void viewport(float width, int lines, AnswerLayout.Measurer measurer) {
        if (measurer == null || !Float.isFinite(width) || width <= 0 || lines < 1) {
            throw new IllegalArgumentException("invalid answer viewport");
        }
        this.width = width;
        this.lines = lines;
        this.measurer = measurer;
        reflow();
    }

    private void reflow() {
        if (!hasViewport()) return;
        if (continuous) { reflowContinuous(); return; }
        AnswerItem item = current();
        String content = content(item);
        pages = null;
        pages = AnswerLayout.paginate(content, width, lines, measurer);
        contentLength = content.length();
        textPageCount = content.isEmpty() && !item.diagrams.isEmpty() ? 0 : pages.size();
        pageIndex = 0;
        if (anchorOffset > contentLength && !item.diagrams.isEmpty()) {
            pageIndex = textPageCount + Math.min(item.diagrams.size()-1, anchorOffset-contentLength-1);
        } else {
            int low = 0;
            int high = textPageCount - 1;
            while (low < high) {
                int middle = low + (high - low) / 2;
                if (pages.get(middle).end <= anchorOffset) low = middle + 1;
                else high = middle;
            }
            pageIndex = low;
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
        sections.clear();
        continuousPageCount = 0;
        int first = 0;
        while (first < bundle.items.size()) {
            int last = first;
            while (last + 1 < bundle.items.size() && bundle.items.get(last).diagrams.isEmpty()) last++;
            StringBuilder text = new StringBuilder();
            int[] starts = new int[last - first + 1];
            int[] bodyStarts = new int[starts.length];
            int lastContentLength = 0;
            int lineStart = 0;
            boolean previousCompact = false;
            for (int i = first; i <= last; i++) {
                AnswerItem item = bundle.items.get(i);
                String body = content(item);
                String label = item.readingLabel();
                boolean compact = item.status == AnswerItem.Status.READY && item.diagrams.isEmpty()
                        && !body.contains("\n") && !body.contains("\r");
                String entry = compact ? label + " " + body : "";
                compact = compact && measurer.width(entry) <= width;
                if (i > first) {
                    if (previousCompact && compact
                            && measurer.width(text.substring(lineStart) + "　" + entry) <= width) {
                        text.append('　');
                    } else {
                        text.append('\n');
                        lineStart = text.length();
                    }
                }
                starts[i - first] = text.length();
                text.append(label).append(' ');
                bodyStarts[i - first] = text.length();
                text.append(body);
                lastContentLength = body.length();
                previousCompact = compact;
            }
            AnswerItem item = bundle.items.get(last);
            String sectionText = text.toString();
            // The line index may be large, so release the mutable text buffer first.
            text = null;
            ContinuousSection section = new ContinuousSection(first, continuousPageCount,
                    AnswerLayout.paginate(sectionText, width, lines, measurer),
                    starts, bodyStarts, lastContentLength, item.diagrams);
            sections.add(section);
            continuousPageCount += section.pages.size() + item.diagrams.size();
            first = last + 1;
        }
        pageIndex = 0;
        int low = 0;
        int high = continuousPageCount - 1;
        while (low <= high) {
            int middle = low + (high - low) / 2;
            ContinuousSection section = sectionAt(middle);
            int owner = section.question(middle);
            if (owner < targetQuestion || (owner == targetQuestion
                    && section.offset(middle) <= targetOffset)) {
                pageIndex = middle;
                low = middle + 1;
            } else high = middle - 1;
        }
        questionIndex = targetQuestion;
        anchorOffset = targetOffset;
    }

    private void selectContinuousPage() {
        ContinuousSection section = sectionAt(pageIndex);
        questionIndex = section.question(pageIndex);
        anchorOffset = section.offset(pageIndex);
    }

    private ContinuousSection sectionAt(int page) {
        int low = 0;
        int high = sections.size() - 1;
        while (low < high) {
            int middle = low + (high - low + 1) / 2;
            if (sections.get(middle).firstPage <= page) low = middle;
            else high = middle - 1;
        }
        return sections.get(low);
    }

    /** Store question boundaries once; page text and ownership are resolved on demand. */
    private static final class ContinuousSection {
        final int firstQuestion;
        final int firstPage;
        final List<AnswerLayout.Page> pages;
        final int[] starts;
        final int[] bodyStarts;
        final int lastContentLength;
        final List<AnswerDiagram> diagrams;

        ContinuousSection(int firstQuestion, int firstPage, List<AnswerLayout.Page> pages,
                          int[] starts, int[] bodyStarts, int lastContentLength,
                          List<AnswerDiagram> diagrams) {
            this.firstQuestion = firstQuestion;
            this.firstPage = firstPage;
            this.pages = pages;
            this.starts = starts;
            this.bodyStarts = bodyStarts;
            this.lastContentLength = lastContentLength;
            this.diagrams = diagrams;
        }

        private int owner(int start) {
            int low = 0;
            int high = starts.length - 1;
            while (low < high) {
                int middle = low + (high - low + 1) / 2;
                if (starts[middle] <= start) low = middle;
                else high = middle - 1;
            }
            return low;
        }

        int question(int globalPage) {
            int localPage = globalPage - firstPage;
            int index = localPage < pages.size() ? owner(pages.get(localPage).start) : starts.length - 1;
            return firstQuestion + index;
        }

        int offset(int globalPage) {
            int localPage = globalPage - firstPage;
            if (localPage >= pages.size()) return lastContentLength + 1 + localPage - pages.size();
            int start = pages.get(localPage).start;
            return Math.max(0, start - bodyStarts[owner(start)]);
        }
    }

    public boolean accept(AnswerBundle next) {
        if (!bundle.sessionId.equals(next.sessionId) || !bundle.inputDigest.equals(next.inputDigest)
                || next.revision <= bundle.revision) return false;
        boolean sameShape = next.items.size() == bundle.items.size();
        for (int i = 0; sameShape && i < bundle.items.size(); i++) {
            AnswerItem old = bundle.items.get(i);
            AnswerItem item = next.items.get(i);
            sameShape = old.questionId.equals(item.questionId) && old.groupId.equals(item.groupId)
                    && old.groupLabel.equals(item.groupLabel) && old.questionLabel.equals(item.questionLabel)
                    && old.answerNumbers.equals(item.answerNumbers);
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
                if (continuous || !hasViewport()) return;
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
        if (continuous) return;
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
