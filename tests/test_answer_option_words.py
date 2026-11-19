"""A choice both reads agree on is shown as its label alone (2026-11-19).

The operator, after two subjects that day: fewer page turns. From 2026-11-18 a choice is answered with its printed
label and the option's words behind it in brackets, because soft two-digit labels are misread and the words let the
wearer find the option. For a label of one digit that both reads gave alike the words only take room: of the day's
answers 82 were of that form, and without the words the answers of the two booklets of choices are 96 characters
where they were 243 and 152 where they were 416, three or four to a row of the glasses where one or two stood. The words stay for a label of two digits, for an answer that is to be checked,
and for anything that is not such a choice. Every example is made up.
"""
import pytest

from tests.test_chatgpt_work import BrowserReply
from tests.test_first_read_out import answer, bundle, question
from tests.test_retake_after_answers import Rounds
from tests.test_route_order import Chat, booklet
from tests.test_work_bridge import client as _client_fixture

client = _client_fixture


def shown(client, monkeypatch, text, **extras):
    one = question("問1", 1)
    _, session = booklet(client, monkeypatch, Rounds((None, [(one, answer(one, text, **extras))])), BrowserReply(), Chat())
    return bundle(client, session)["items"][0]["answer"]


@pytest.mark.parametrize("text, expected", [
    ("③（光合成）", "③"),
    ("ア：③（光合成）\nイ：①（蒸散）", "ア：③\nイ：①"),
    ("⑫（光合成）", "⑫（光合成）"),                       # two digits: the words are what the wearer goes by
    ("ア：③（光合成）\nイ：⑫（蒸散）", "ア：③\nイ：⑫（蒸散）"),
    ("③", "③"),
    ("光合成（明反応）", "光合成（明反応）"),               # not a choice
    ("③（光合成）である", "③（光合成）である"),
    ("f(x) = ③（x）", "f(x) = ③（x）"),
])
def test_the_words_of_an_agreed_single_digit_choice_are_left_out(client, monkeypatch, text, expected):
    assert shown(client, monkeypatch, text) == expected


def test_an_answer_to_be_checked_keeps_its_words(client, monkeypatch):
    assert shown(client, monkeypatch, "③（光合成）", review_note="2回の読みで不一致。他方：④", other_answer="④（呼吸）") == "③（光合成）"
