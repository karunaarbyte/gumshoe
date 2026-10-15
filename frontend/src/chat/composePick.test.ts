import { describe, expect, test } from "vitest";
import type { ChatMessage } from "../game/model";
import { composePick } from "./composePick";

const player = (text: string): ChatMessage => ({
  id: "p",
  turn: 0,
  kind: "player",
  text,
  via: "turn",
});
const clarify = (reason: "accusation" | "low_confidence"): ChatMessage => ({
  id: "c",
  turn: 0,
  kind: "clarify",
  event: {
    kind: "clarify",
    reason,
    text: "?",
    decision_id: null,
    problems: [],
  },
});

describe("composePick", () => {
  test("a pick after an accusation clarify carries the accusation so far", () => {
    expect(
      composePick(
        [player("I accuse Gilbert the cook"), clarify("accusation")],
        "I think it was out of faith",
      ),
    ).toBe("I accuse Gilbert the cook. I think it was out of faith");
  });

  test("the composed line is what the next pick builds on, without doubled full stops", () => {
    expect(
      composePick(
        [
          player("I accuse Gilbert. I think it was a rope."),
          clarify("accusation"),
        ],
        "x",
      ),
    ).toBe("I accuse Gilbert. I think it was a rope. x");
  });

  test("outside an accusation clarify the pick is sent as it is", () => {
    expect(
      composePick([player("hello"), clarify("low_confidence")], "pick"),
    ).toBe("pick");
    expect(composePick([], "pick")).toBe("pick");
  });
});
