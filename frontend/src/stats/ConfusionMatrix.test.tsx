import { render, screen, within } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import type { NodeStats } from "../api/types";
import { statsReport } from "../test/fakeApi";
import { ConfusionMatrix } from "./ConfusionMatrix";

const understand = statsReport.nodes.find(
  (n) => n.node === "understand",
) as NodeStats;

describe("ConfusionMatrix", () => {
  test("rows are the primary and columns the shadow, named from the roles", () => {
    render(<ConfusionMatrix node={understand} />);
    expect(screen.getByRole("table")).toHaveAccessibleName(
      /what jev chose \(rows\) against what nimble chose \(columns\)/,
    );
  });

  test("every cell carries its count and its meaning as text, not just colour", () => {
    render(<ConfusionMatrix node={understand} />);
    expect(
      screen.getByLabelText("jev chose search, nimble chose search: 14"),
    ).toHaveAttribute("data-kind", "match");
    expect(
      screen.getByLabelText("jev chose search, nimble chose records: 3"),
    ).toHaveAttribute("data-kind", "differ");
    expect(
      screen.getByLabelText("jev chose search, nimble chose records: 3"),
    ).toHaveTextContent("≠ 3");
  });

  test("the shadow-failed column comes last and counts decisions no agreement figure includes", () => {
    render(<ConfusionMatrix node={understand} />);
    const headers = screen
      .getAllByRole("columnheader")
      .map((h) => h.textContent);
    expect(headers.at(-1)).toBe("nimble failed");
    const cell = screen.getByLabelText("jev chose search, nimble failed: 42");
    expect(cell).toHaveAttribute("data-kind", "error");
  });

  test("an empty cell is a quiet dot", () => {
    render(<ConfusionMatrix node={understand} />);
    expect(
      screen.getByLabelText("jev chose accuse, nimble chose meta: 0"),
    ).toHaveTextContent("·");
  });

  test("a node without an intent question has no matrix", () => {
    const post = statsReport.nodes.find(
      (n) => n.node === "post_check",
    ) as NodeStats;
    const { container } = render(<ConfusionMatrix node={post} />);
    expect(container).toBeEmptyDOMElement();
  });

  test("rows have header cells", () => {
    render(<ConfusionMatrix node={understand} />);
    const rowHeaders = screen
      .getAllByRole("rowheader")
      .map((h) => h.textContent);
    expect(rowHeaders).toEqual([
      "accuse",
      "give_up",
      "interrogate",
      "records",
      "search",
    ]);
    expect(
      within(screen.getAllByRole("row")[1]!).getAllByRole("cell").length,
    ).toBeGreaterThan(3);
  });
});
