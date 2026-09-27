"use strict";

const fs = require("fs");
const input = fs.readFileSync(0, "utf8");
let index = 0;

function nextInt() {
  while (index < input.length && input.charCodeAt(index) <= 32) index += 1;
  let sign = 1;
  if (input.charCodeAt(index) === 45) {
    sign = -1;
    index += 1;
  } else if (input.charCodeAt(index) === 43) {
    index += 1;
  }
  let value = 0;
  while (index < input.length) {
    const code = input.charCodeAt(index);
    if (code < 48 || code > 57) break;
    value = value * 10 + code - 48;
    index += 1;
  }
  return sign * value;
}

const counts = Array(7).fill(0);
for (let card = 0; card < 3; card += 1) counts[nextInt()] += 1;

let value = 1;
let frequency = 0;
for (let candidate = 1; candidate <= 6; candidate += 1) {
  if (counts[candidate] >= frequency) {
    frequency = counts[candidate];
    value = candidate;
  }
}

if (frequency === 3) {
  console.log(10000 + value * 1000);
} else if (frequency === 2) {
  console.log(1000 + value * 100);
} else {
  console.log(value * 100);
}
