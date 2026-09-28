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

const count = nextInt();
let minimum = nextInt();
let maximum = minimum;
for (let item = 1; item < count; item += 1) {
  const value = nextInt();
  if (value < minimum) minimum = value;
  if (value > maximum) maximum = value;
}
console.log(`${minimum} ${maximum}`);
