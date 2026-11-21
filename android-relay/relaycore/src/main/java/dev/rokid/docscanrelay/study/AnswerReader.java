package dev.rokid.docscanrelay.study;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

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
    private AnswerDiagram.Numbering numbering;
    private List<AnswerLayout.Page> pages;
    private int textPageCount;
    private int contentLength;
    private Screen screen = Screen.ANSWER;
    private int menuIndex;
    private String menuGroup;
    private final boolean continuous;
    private final List<ContinuousSection> sections = new ArrayList<>();
    private int continuousPageCount;
    // Continuous reading shows the answers in the paper's order, which is the bundle's; then the screen that says
    // what to photograph again; then what has no answer yet (being analysed, failed); then, after pages were added,
    // the answers the wearer already had. A question that cannot be answered, or that the two reads do not settle,
    // is not shown: its capture is on the retake screen (the operator, 2026-11-19 and 2026-11-21). The bundle's
    // order stays the questions' identity; these say where each one is shown.
    private static final String RETAKE = "再撮影";
    /** Bundle index to place in the display order; -1 for a question that is not shown. */
    private int[] entryOf;
    /** Place in the display order to bundle index. */
    private int[] questionOf;
    /** The place of the one screen that belongs to no question (what to retake, or "no answer"), or -1. */
    private int pseudoEntry;
    private int pseudoPage;
    /** The reader stands on the retake screen; its place is kept as a neighbouring question. */
    private boolean onRetake;

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
        arrange();
        firstScreen();
    }

    /** 0 an answer, 2 no answer yet, 3 already had; -1 not shown: a notice, or a question whose pages are to be retaken. */
    private static int part(AnswerItem item) {
        if (item.notice() || item.status == AnswerItem.Status.NEEDS_INPUT || item.uncertain) return -1;
        // An answer to check for its form alone (a table the display cannot carry) is an answer, shown as it is.
        if (item.status != AnswerItem.Status.READY && item.status != AnswerItem.Status.NEEDS_REVIEW) return 2;
        return item.seen ? 3 : 0;
    }

    /** The display order; it needs no viewport, so a saved place can be settled before a view has a size. */
    private void arrange() {
        if (!continuous) return;
        int size = bundle.items.size();
        entryOf = new int[size];
        Arrays.fill(entryOf, -1);
        int[] order = new int[size + 1];
        int count = 0;
        pseudoEntry = -1;
        for (int part = 0; part < 4; part++) {
            if (part == 1) {
                if (!bundle.retake.isEmpty()) pseudoEntry = count++;
                continue;
            }
            for (int i = 0; i < size; i++) {
                if (part(bundle.items.get(i)) == part) {
                    entryOf[i] = count;
                    order[count++] = i;
                }
            }
        }
        if (count == 0) pseudoEntry = count++;
        // A place on that screen is kept as the question shown just before it, else the one after it.
        if (pseudoEntry >= 0) order[pseudoEntry] = pseudoEntry > 0 ? order[pseudoEntry - 1] : count > 1 ? order[1] : 0;
        questionOf = Arrays.copyOf(order, count);
    }

    private void firstScreen() {
        questionIndex = continuous ? questionOf[0] : 0;
        anchorOffset = 0;
        onRetake = continuous && pseudoEntry == 0 && !bundle.retake.isEmpty();
    }

    /** A question that is not shown gives its place to the nearest shown one before it, else to the first screen. */
    private void settle() {
        if (!continuous) return;
        onRetake = onRetake && !bundle.retake.isEmpty();
        if (onRetake) {
            questionIndex = questionOf[pseudoEntry];
            anchorOffset = 0;
        } else if (entryOf[questionIndex] < 0) {
            int earlier = questionIndex - 1;
            while (earlier >= 0 && entryOf[earlier] < 0) earlier--;
            if (earlier < 0) { firstScreen(); return; }
            questionIndex = earlier;
            anchorOffset = 0;
        }
    }

    public AnswerBundle bundle() { return bundle; }
    public boolean hasViewport() { return measurer != null; }
    public AnswerItem current() { return bundle.items.get(questionIndex); }
    /** Capture pages (1-based) the wearer should photograph again. */
    public List<Integer> retakePages() { return bundle.retake; }
    /** The reader stands on the screen that lists them: there a double tap takes them, elsewhere it ends the writing. */
    public boolean onRetakeScreen() { return continuous && onRetake && !bundle.retake.isEmpty(); }
    /** A second read is still being compared with these answers. */
    public boolean comparing() { return bundle.comparing; }
    /** What the index row names: the question at the top of the screen, or the screen that belongs to none. */
    public String indexLabel() {
        if (onRetake) return RETAKE;
        return continuous && entryOf[questionIndex] < 0 ? "" : current().readingLabel();
    }
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
        return pageIndex < textPageCount ? pages.get(pageIndex).start
                : contentLength + 1 + pageIndex - textPageCount;
    }

    /** The view also says which labels its figures show as numbers; only those are listed before a figure. */
    public void viewport(float width, int lines, AnswerLayout.Measurer measurer, AnswerDiagram.Numbering numbering) {
        this.numbering = numbering;
        viewport(width, lines, measurer);
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

    private String content(AnswerItem item) {
        String content;
        switch (item.status) {
            case READY: content = item.answer; break;
            // Continuous reading shows the answer alone, with no mark and no sentence (operator, 2026-11-19 and
            // 2026-11-21); what the two reads do not settle never comes here (part). The reader with menus, which
            // no screen of the app uses, warns first so the operator knows the answer is incomplete before copying
            // it, and the answer still follows.
            case NEEDS_REVIEW:
                content = !continuous ? "【要確認】" + item.issue + "\n" + item.answer : item.answer;
                break;
            // Not shown in continuous reading: its pages are on the retake screen.
            case NEEDS_INPUT: content = "資料不足\n" + item.issue; break;
            case FAILED: content = "解析できません\n" + item.issue; break;
            default: content = "解析中"; break;
        }
        for (int i = 0; i < item.diagrams.size(); i++) content += item.diagrams.get(i).readingText(i + 1, numbering);
        return content;
    }

    /**
     * Pack adjacent text answers in the display order; a figure remains a page of its own behind its answer, and
     * the screen that belongs to no question stands alone.
     */
    private void reflowContinuous() {
        sections.clear();
        continuousPageCount = 0;
        int first = 0;
        while (first < questionOf.length) {
            boolean pseudo = first == pseudoEntry;
            int last = first;
            while (!pseudo && last + 1 < questionOf.length && last + 1 != pseudoEntry
                    && bundle.items.get(questionOf[last]).diagrams.isEmpty()) last++;
            StringBuilder text = new StringBuilder();
            int[] starts = new int[last - first + 1];
            int[] bodyStarts = new int[starts.length];
            int lastContentLength = 0;
            int lineStart = 0;
            boolean previousCompact = false;
            boolean previousSeen = false;
            List<AnswerDiagram> diagrams = Collections.emptyList();
            if (pseudo) {
                pseudoPage = continuousPageCount;
                text.append(bundle.retake.isEmpty() ? "解答なし" : retakeText());
            }
            for (int entry = first; !pseudo && entry <= last; entry++) {
                AnswerItem item = bundle.items.get(questionOf[entry]);
                String body = content(item);
                String label = item.readingLabel();
                boolean compact = item.status == AnswerItem.Status.READY && item.diagrams.isEmpty()
                        && !body.contains("\n") && !body.contains("\r");
                String row = compact ? label + " " + body : "";
                compact = compact && measurer.width(row) <= width;
                if (entry > first) {
                    // Answers the wearer already had begin a row of their own behind the others.
                    if (previousCompact && compact && item.seen == previousSeen
                            && measurer.width(text.substring(lineStart) + "　" + row) <= width) {
                        text.append('　');
                    } else {
                        text.append('\n');
                        lineStart = text.length();
                    }
                }
                starts[entry - first] = text.length();
                text.append(label).append(' ');
                bodyStarts[entry - first] = text.length();
                text.append(body);
                lastContentLength = body.length();
                previousCompact = compact;
                previousSeen = item.seen;
                diagrams = item.diagrams;
            }
            String sectionText = text.toString();
            // The line index may be large, so release the mutable text buffer first.
            text = null;
            ContinuousSection section = new ContinuousSection(first, continuousPageCount, pseudo,
                    AnswerLayout.paginate(sectionText, width, lines, measurer),
                    starts, bodyStarts, lastContentLength, diagrams);
            sections.add(section);
            continuousPageCount += section.pages.size() + diagrams.size();
            first = last + 1;
        }
        pageIndex = onRetake ? pseudoPage : 0;
        if (onRetake) return;
        // Pages rise with the place in the display order, not with the bundle index.
        int target = entryOf[questionIndex];
        int low = 0;
        int high = continuousPageCount - 1;
        while (low <= high) {
            int middle = low + (high - low) / 2;
            ContinuousSection section = sectionAt(middle);
            int owner = section.entry(middle);
            if (owner < target || (owner == target && section.offset(middle) <= anchorOffset)) {
                pageIndex = middle;
                low = middle + 1;
            } else high = middle - 1;
        }
    }

    /** "再撮影 3・8・9": a row ends between two page numbers, never inside one. */
    private String retakeText() {
        StringBuilder text = new StringBuilder(RETAKE).append(' ');
        int lineStart = 0;
        for (int i = 0; i < bundle.retake.size(); i++) {
            String number = bundle.retake.get(i) + (i + 1 < bundle.retake.size() ? "・" : "");
            if (text.length() > lineStart && measurer.width(text.substring(lineStart) + number) > width) {
                text.append('\n');
                lineStart = text.length();
            }
            text.append(number);
        }
        return text.append("\nダブルタップで撮影").toString();
    }

    private void selectContinuousPage() {
        ContinuousSection section = sectionAt(pageIndex);
        questionIndex = questionOf[section.entry(pageIndex)];
        anchorOffset = section.pseudo ? 0 : section.offset(pageIndex);
        onRetake = section.pseudo && !bundle.retake.isEmpty();
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
        /** Place of its first question in the display order. */
        final int firstEntry;
        final int firstPage;
        /** The screen that belongs to no question. */
        final boolean pseudo;
        final List<AnswerLayout.Page> pages;
        final int[] starts;
        final int[] bodyStarts;
        final int lastContentLength;
        final List<AnswerDiagram> diagrams;

        ContinuousSection(int firstEntry, int firstPage, boolean pseudo, List<AnswerLayout.Page> pages,
                          int[] starts, int[] bodyStarts, int lastContentLength,
                          List<AnswerDiagram> diagrams) {
            this.firstEntry = firstEntry;
            this.firstPage = firstPage;
            this.pseudo = pseudo;
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

        int entry(int globalPage) {
            int localPage = globalPage - firstPage;
            int index = localPage < pages.size() ? owner(pages.get(localPage).start) : starts.length - 1;
            return firstEntry + index;
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
        boolean changed = continuous && !bundle.retake.equals(next.retake);
        for (int i = 0; sameShape && i < bundle.items.size(); i++) {
            AnswerItem old = bundle.items.get(i);
            AnswerItem item = next.items.get(i);
            sameShape = old.questionId.equals(item.questionId) && old.groupId.equals(item.groupId)
                    && old.groupLabel.equals(item.groupLabel) && old.questionLabel.equals(item.questionLabel)
                    && old.answerNumbers.equals(item.answerNumbers);
            // Continuous pages contain every item; ordinary pages only contain the current one.
            if (continuous || i == questionIndex) {
                changed = changed || !old.answer.equals(item.answer)
                        || old.status != item.status || !old.issue.equals(item.issue)
                        || !old.diagrams.equals(item.diagrams) || !old.other.equals(item.other)
                        || old.seen != item.seen;
            }
        }
        if (!sameShape) {
            // The same questions never change order or what the paper prints for them. Questions may come
            // and go around them: the comparison of two reads adds what only the second read listed and
            // takes its notice away. Group ids are positions and may move with that; group labels may not.
            // A deck with none of the old question ids is a replacement: the one row a failed message
            // left, replaced by the model's list on a retry.
            Map<String, Integer> places = new HashMap<>();
            for (int i = 0; i < next.items.size(); i++) places.put(next.items.get(i).questionId, i);
            int last = -1;
            int stay = -1;
            boolean here = false;
            for (int i = 0; i < bundle.items.size(); i++) {
                AnswerItem old = bundle.items.get(i);
                Integer place = places.get(old.questionId);
                if (place == null) continue;
                AnswerItem item = next.items.get(place);
                if (place < last || !old.groupLabel.equals(item.groupLabel)
                        || !old.questionLabel.equals(item.questionLabel)
                        || !old.answerNumbers.equals(item.answerNumbers)) return false;
                last = place;
                // The question being read, or the nearest one before it that is still there.
                if (i <= questionIndex) { stay = place; here = i == questionIndex; }
            }
            bundle = next;
            arrange();
            if (stay < 0) firstScreen();
            else {
                questionIndex = stay;
                if (!here) anchorOffset = 0;
                settle(); // the question may have stopped being shown, or moved to another section
            }
            screen = Screen.ANSWER;
            menuIndex = 0;
            menuGroup = null;
            reflow();
            return true;
        }
        bundle = next;
        if (changed) {
            arrange();
            settle();
            reflow();
        }
        return true;
    }

    public void restore(String questionId, int offset) {
        for (int i = 0; i < bundle.items.size(); i++) {
            if (bundle.items.get(i).questionId.equals(questionId)) {
                questionIndex = i;
                anchorOffset = Math.max(0, offset);
                onRetake = false;
                // A reading not yet begun is saved as the bundle's first question at its start (AnswerStore.start):
                // that is the first screen, wherever that question is shown.
                if (i == 0 && anchorOffset == 0) firstScreen();
                else settle();
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
        } else if (continuous) {
            // Past the last screen comes the first (operator, 2026-11-19).
            if (pageCount() > 1) {
                pageIndex = (pageIndex + 1) % pageCount();
                selectContinuousPage();
            }
        } else if (pageIndex + 1 < pageCount()) {
            pageIndex++;
            anchorOffset = pageStart();
        } else if (questionIndex + 1 < bundle.items.size()) {
            questionIndex++;
            anchorOffset = 0;
            reflow();
        }
    }

    public void backward() {
        if (screen != Screen.ANSWER) {
            menuIndex = Math.max(menuIndex - 1, 0);
        } else if (continuous) {
            if (pageCount() > 1) {
                pageIndex = (pageIndex + pageCount() - 1) % pageCount();
                selectContinuousPage();
            }
        } else if (pageIndex > 0) {
            pageIndex--;
            anchorOffset = pageStart();
        } else if (questionIndex > 0) {
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
