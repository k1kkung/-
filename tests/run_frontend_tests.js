"use strict";

const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const storage = new Map();
const window = {
  localStorage: {
    getItem: (key) => (storage.has(key) ? storage.get(key) : null),
    setItem: (key, value) => storage.set(key, String(value)),
    removeItem: (key) => storage.delete(key),
  },
};
const context = {
  window,
  console,
  Promise,
  Date,
  setTimeout,
  clearTimeout,
  URLSearchParams,
};

vm.createContext(context);
vm.runInContext(fs.readFileSync("stories.js", "utf8"), context);
vm.runInContext(fs.readFileSync("app.js", "utf8"), context);

const engine = context.window.HaiTangEngine;
assert(engine, "HaiTangEngine should be available");

assert.strictEqual(
  engine.localJudge("socks-in-freezer", "急救志愿者"),
  "yes"
);
assert.strictEqual(
  engine.localJudge("socks-in-freezer", "袜子是食物"),
  "no"
);
assert.strictEqual(
  engine.localJudge("socks-in-freezer", "完全无关的问题"),
  "irrelevant"
);
assert.strictEqual(
  engine.isClearlyOpenQuestion("老人为什么笑？"),
  true
);
assert.strictEqual(
  engine.isClearlyOpenQuestion("名单是谁发布的？"),
  true
);
assert.strictEqual(
  engine.isClearlyOpenQuestion("收音机真的能预报死亡吗？"),
  false
);
assert.strictEqual(
  engine.isClearlyOpenQuestion("是/不是：她知道发生了什么吗？"),
  false
);

const factGroups = engine.partitionRevealFacts([
  { description: "true fact", truth: true },
  { description: "false fact", truth: false },
]);
assert.strictEqual(factGroups.confirmed.length, 1);
assert.strictEqual(factGroups.confirmed[0].description, "true fact");
assert.strictEqual(factGroups.confirmed[0].truth, true);
assert.strictEqual(factGroups.excluded.length, 1);
assert.strictEqual(factGroups.excluded[0].description, "false fact");
assert.strictEqual(factGroups.excluded[0].truth, false);

const trainReveal = engine.localReveal("missing-train-passenger");
const trainFacts = engine.partitionRevealFacts(trainReveal.facts);
assert(
  trainFacts.confirmed.every(
    (fact) => fact.description !== "乘客在车上被杀害。"
  )
);
assert(
  trainFacts.excluded.some(
    (fact) => fact.description === "乘客在车上被杀害。"
  )
);

const source = fs.readFileSync("app.js", "utf8");
const html = fs.readFileSync("index.html", "utf8");
assert(source.includes('unknown: "无法判断"'));
assert(source.includes('answer !== "unknown"'));
assert(source.includes('"judge",'));
assert(source.includes('[storyId, question, history]'));
assert(html.includes('id="hintSuggestion"'));
assert(!html.includes('id="suggestionBox"'));

const localHint = engine.localHint("socks-in-freezer", 0, false);
assert(localHint);
assert(localHint.suggested_question);

console.log("frontend judge tests passed");
