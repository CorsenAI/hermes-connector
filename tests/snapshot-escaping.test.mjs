import assert from "node:assert/strict";
import { runInNewContext } from "node:vm";
import test from "node:test";
import { buildSnapshot } from "../extension/src/page-actions.js";

const labels = [
  "ordinary chars 123",
  'He said "hi"',
  "C:\\path",
  "ends with backslash\\",
  '"quoted\\" inside"',
  "Crème שלום 日本語",
];

// Small DOM fixture, not a replacement snapshot implementation. The production
// function is serialized just as it is for chrome.scripting.executeScript.
function snapshot(functionSource, names = labels) {
  const element = (tagName, name = null) => ({
    tagName,
    childNodes: [],
    children: [],
    getAttribute(key) { return key === "aria-label" ? name : null; },
    checkVisibility() { return true; },
    getBoundingClientRect() {
      return { top: 0, left: 0, right: 100, bottom: 30, width: 100, height: 30 };
    },
  });
  const body = element("BODY");
  body.children = names.map((name) => element("BUTTON", name));
  const context = {
    window: {},
    document: { body, title: "Snapshot fixture" },
    location: { href: "https://example.test/snapshot" },
    innerWidth: 1280,
    innerHeight: 900,
    URL,
    URLSearchParams,
    getComputedStyle() {
      return { display: "block", opacity: "1", visibility: "visible", contentVisibility: "visible" };
    },
  };
  return runInNewContext(`(${functionSource})(50000)`, context, { timeout: 1000 });
}

function assertNames(result, names) {
  const lines = result.content.split("\n");
  assert.equal(lines.length, names.length, "one snapshot line per fixture button");
  names.forEach((name, index) => {
    // JSON encoding is an independent oracle for the quoted names in this
    // fixture; no copy of the production replace expression is used here.
    const expected = `button ${JSON.stringify(name)} [ref_${index + 1}]`;
    assert.equal(lines[index], expected, `snapshot label ${index}`);
    const quoted = lines[index].slice("button ".length, lines[index].lastIndexOf(" [ref_"));
    assert.equal(JSON.parse(quoted), name, "quoted label must round-trip");
  });
  assert.equal(result.truncated, false);
}

test("serialized buildSnapshot preserves quotes, backslashes and Unicode names", () => {
  assertNames(snapshot(buildSnapshot.toString()), labels);
});

test("snapshot regression detects the former quote-only escaping", () => {
  const source = buildSnapshot.toString();
  const addedEscape = String.raw`name.replace(/\\/g, "\\\\").replace`;
  assert.equal(source.split(addedEscape).length, 2, "exactly one escape expression is mutated");
  const formerSource = source.replace(addedEscape, "name.replace");
  const result = snapshot(formerSource);
  // A crash is not a successful negative control: the old function must run
  // and produce a snapshot whose backslash-bearing names are wrong.
  assert.equal(result.content.split("\n").length, labels.length);
  assert.throws(() => assertNames(result, labels), assert.AssertionError);
  const lines = result.content.split("\n");
  const mismatches = labels.flatMap((name, index) =>
    lines[index] === `button ${JSON.stringify(name)} [ref_${index + 1}]` ? [] : [index]);
  assert.deepEqual(mismatches, [2, 3, 4]);
});
