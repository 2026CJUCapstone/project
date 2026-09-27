"use strict";

const fs = require("fs");
const input = fs.readFileSync(0, "utf8");
let index = 0;

function nextToken() {
  while (index < input.length && input.charCodeAt(index) <= 32) index += 1;
  const start = index;
  while (index < input.length && input.charCodeAt(index) > 32) index += 1;
  return input.slice(start, index);
}

const caseCount = Number(nextToken());
const output = [];
for (let testCase = 0; testCase < caseCount; testCase += 1) {
  const repeats = Number(nextToken());
  const phrase = nextToken();
  let expanded = "";
  for (const character of phrase) expanded += character.repeat(repeats);
  output.push(expanded);
}
console.log(output.join("\n"));
