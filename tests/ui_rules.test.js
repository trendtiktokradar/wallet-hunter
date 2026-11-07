"use strict";
const assert = require("assert");
const R = require("../web/rules.js");

const known = {};
R.NOISE.forEach((id) => { known[id] = { id: id }; });
known.rentable = { id: "rentable" };

function cycle3(id) {
  let tags = [], xtags = [];
  let a = R.cycle(tags, xtags, id);
  assert.deepStrictEqual(a.state, "inc");
  assert.deepStrictEqual(a.tags, [id]);
  assert.deepStrictEqual(a.xtags, []);
  let b = R.cycle(a.tags, a.xtags, id);
  assert.deepStrictEqual(b.state, "exc");
  assert.deepStrictEqual(b.tags, []);
  assert.deepStrictEqual(b.xtags, [id]);
  let c = R.cycle(b.tags, b.xtags, id);
  assert.deepStrictEqual(c.state, "");
  assert.deepStrictEqual(c.tags, []);
  assert.deepStrictEqual(c.xtags, []);
}

cycle3("bot");
cycle3("rentable");

assert.strictEqual(R.passesTags(["bot", "sniper"], ["bot", "sniper"], [], null), true);
assert.strictEqual(R.passesTags(["bot"], ["bot", "rentable"], [], null), false);
assert.strictEqual(R.passesTags(["bot", "sniper"], [], ["bot"], null), false);
assert.strictEqual(R.passesTags(["sniper"], ["sniper"], ["bot"], null), true);
assert.strictEqual(R.passesTags(["bot"], [], ["bot"], "bot"), true);

let tags = ["rentable", "bot"];
let xtags = ["sniper"];
let hidden = R.toggleNoise(tags, xtags, R.NOISE, known);
assert.strictEqual(hidden.hidden, true);
assert.deepStrictEqual(hidden.tags, ["rentable"]);
R.NOISE.forEach((id) => assert.ok(hidden.xtags.includes(id), id));
assert.ok(!hidden.xtags.includes("rentable"));
let back = R.toggleNoise(hidden.tags, hidden.xtags, R.NOISE, known);
assert.strictEqual(back.hidden, false);
assert.deepStrictEqual(back.tags, ["rentable"]);
R.NOISE.forEach((id) => assert.ok(!back.xtags.includes(id)));

const evil = R.esc('"><img src=x onerror=alert(1)>');
assert.ok(!evil.includes("<"));
assert.ok(!evil.includes(">"));
assert.ok(!evil.includes('"'));
assert.ok(evil.includes("&lt;"));
assert.ok(evil.includes("&#39;") || !evil.includes("'"));

console.log("ui rules ok");
