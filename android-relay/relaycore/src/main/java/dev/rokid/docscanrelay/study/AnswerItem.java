package dev.rokid.docscanrelay.study;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/** A single answer-sheet entry. Issue text is never part of the written answer. */
public final class AnswerItem {
    /**
     * NEEDS_REVIEW carries an answer AND an issue: the server converted what it
     * could for the display and named the element it could not carry (a table,
     * a figure, unknown notation). Such an answer is never READY, because the
     * operator would otherwise copy an incomplete one without knowing.
     */
    public enum Status { PENDING, READY, NEEDS_REVIEW, NEEDS_INPUT, FAILED }

    public final String groupId;
    public final String groupLabel;
    public final String questionId;
    public final String questionLabel;
    public final String answer;
    public final Status status;
    public final String issue;
    public final List<AnswerDiagram> diagrams;
    public final List<Integer> answerNumbers;
    /** The other read's answer where two reads disagree; kept for NEEDS_REVIEW only, else "". */
    public final String other;
    /** The wearer already had this exact answer before pages were added. */
    public final boolean seen;
    /**
     * The two reads of the booklet do not settle this answer: they differ, or one of them alone gave it. The reader
     * shows no such answer; the bundle lists its capture among those to take again. The server marks it
     * ({@code uncertain}); a bundle from a server before that mark is told by its note, which begins with 2回.
     */
    public final boolean uncertain;

    public AnswerItem(String groupId, String groupLabel, String questionId, String questionLabel,
                      String answer, Status status, String issue) {
        this(groupId, groupLabel, questionId, questionLabel, answer, status, issue, Collections.emptyList());
    }

    public AnswerItem(String groupId, String groupLabel, String questionId, String questionLabel,
                      String answer, Status status, String issue, List<AnswerDiagram> diagrams) {
        this(groupId, groupLabel, questionId, questionLabel, answer, status, issue, diagrams, Collections.emptyList());
    }

    public AnswerItem(String groupId, String groupLabel, String questionId, String questionLabel,
                      String answer, Status status, String issue, List<AnswerDiagram> diagrams,
                      List<Integer> answerNumbers) {
        this(groupId, groupLabel, questionId, questionLabel, answer, status, issue, diagrams, answerNumbers, "", false);
    }

    public AnswerItem(String groupId, String groupLabel, String questionId, String questionLabel,
                      String answer, Status status, String issue, List<AnswerDiagram> diagrams,
                      List<Integer> answerNumbers, String other, boolean seen) {
        this(groupId, groupLabel, questionId, questionLabel, answer, status, issue, diagrams, answerNumbers, other, seen, false);
    }

    public AnswerItem(String groupId, String groupLabel, String questionId, String questionLabel,
                      String answer, Status status, String issue, List<AnswerDiagram> diagrams,
                      List<Integer> answerNumbers, String other, boolean seen, boolean uncertain) {
        this.groupId = identifier(groupId);
        this.questionId = identifier(questionId);
        this.groupLabel = label(groupLabel);
        this.questionLabel = label(questionLabel);
        boolean carriesAnswer = status == Status.READY || status == Status.NEEDS_REVIEW;
        if (status == null || answer == null || issue == null || answer.length() > AnswerBundle.MAX_TEXT_CHARS
                || diagrams == null || diagrams.size() > 4 || diagrams.stream().anyMatch(d -> d == null)
                || issue.codePointCount(0, issue.length()) > 1000 || (carriesAnswer && answer.trim().isEmpty() && diagrams.isEmpty())
                || (!carriesAnswer && !answer.isEmpty())
                || (!carriesAnswer && !diagrams.isEmpty())
                || (status == Status.NEEDS_REVIEW && issue.trim().isEmpty())
                || other == null || other.codePointCount(0, other.length()) > 200) {
            throw new IllegalArgumentException("invalid written answer");
        }
        this.answer = answer;
        this.status = status;
        this.issue = status == Status.READY ? "" : issue;
        this.other = status == Status.NEEDS_REVIEW ? other : "";
        this.seen = seen;
        this.uncertain = status == Status.NEEDS_REVIEW && (uncertain || issue.startsWith("2回"));
        this.diagrams = Collections.unmodifiableList(new ArrayList<>(diagrams));
        if (answerNumbers == null || answerNumbers.size() > 1000 || answerNumbers.stream()
                .anyMatch(n -> n == null || n <= 0 || n > 9999)) throw new IllegalArgumentException("invalid answer number");
        this.answerNumbers = Collections.unmodifiableList(new ArrayList<>(answerNumbers));
    }

    public static AnswerItem ready(String groupId, String groupLabel, String questionId,
                                    String questionLabel, String answer) {
        return new AnswerItem(groupId, groupLabel, questionId, questionLabel, answer, Status.READY, "");
    }

    public String readingLabel() {
        if (answerNumbers.isEmpty()) return groupLabel + " " + questionLabel;
        List<String> labels = new ArrayList<>();
        for (Integer number : answerNumbers) labels.add(number.toString());
        return String.join(",", labels);
    }

    /** A notice about the capture from an older server (照合中, 縮小, a page's own): not an answer, never shown. */
    public boolean notice() { return "pages".equals(groupId); }

    public String heading() { return groupLabel + " " + (answerNumbers.isEmpty() ? questionLabel : readingLabel()); }

    static String identifier(String value) {
        if (value == null || !value.matches("[A-Za-z0-9_.-]{1,120}")
                || value.equals(".") || value.equals("..")) {
            throw new IllegalArgumentException("invalid study identifier");
        }
        return value;
    }

    private static String label(String value) {
        if (value == null || value.trim().isEmpty() || value.codePointCount(0, value.length()) > 120) {
            throw new IllegalArgumentException("invalid question label");
        }
        return value;
    }
}
