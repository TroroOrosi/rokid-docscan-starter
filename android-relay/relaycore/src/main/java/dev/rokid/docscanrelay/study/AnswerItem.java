package dev.rokid.docscanrelay.study;

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

    public AnswerItem(String groupId, String groupLabel, String questionId, String questionLabel,
                      String answer, Status status, String issue) {
        this.groupId = identifier(groupId);
        this.questionId = identifier(questionId);
        this.groupLabel = label(groupLabel);
        this.questionLabel = label(questionLabel);
        boolean carriesAnswer = status == Status.READY || status == Status.NEEDS_REVIEW;
        if (status == null || answer == null || issue == null || answer.length() > 200_000
                || issue.length() > 1000 || (carriesAnswer && answer.trim().isEmpty())
                || (!carriesAnswer && !answer.isEmpty())
                || (status == Status.NEEDS_REVIEW && issue.trim().isEmpty())) {
            throw new IllegalArgumentException("invalid written answer");
        }
        this.answer = answer;
        this.status = status;
        this.issue = status == Status.READY ? "" : issue;
    }

    public static AnswerItem ready(String groupId, String groupLabel, String questionId,
                                    String questionLabel, String answer) {
        return new AnswerItem(groupId, groupLabel, questionId, questionLabel, answer, Status.READY, "");
    }

    public String heading() { return groupLabel + " " + questionLabel; }

    static String identifier(String value) {
        if (value == null || !value.matches("[A-Za-z0-9_.-]{1,120}")
                || value.equals(".") || value.equals("..")) {
            throw new IllegalArgumentException("invalid study identifier");
        }
        return value;
    }

    private static String label(String value) {
        if (value == null || value.trim().isEmpty() || value.length() > 120) {
            throw new IllegalArgumentException("invalid question label");
        }
        return value;
    }
}
