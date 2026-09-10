package dev.rokid.docscanrelay.study;

/** A single answer-sheet entry. Issue text is never part of the written answer. */
public final class AnswerItem {
    public enum Status { PENDING, READY, NEEDS_INPUT, FAILED }

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
        if (status == null || answer == null || issue == null || answer.length() > 200_000
                || issue.length() > 1000 || (status == Status.READY && answer.trim().isEmpty())
                || (status != Status.READY && !answer.isEmpty())) {
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
