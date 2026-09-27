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

const columns = nextInt();
const rows = nextInt();
const size = rows * columns;
const cells = new Int8Array(size);
const queue = new Int32Array(size);
let head = 0;
let tail = 0;
let remaining = 0;

for (let position = 0; position < size; position += 1) {
  const value = nextInt();
  cells[position] = value;
  if (value === 1) queue[tail++] = position;
  else if (value === 0) remaining += 1;
}

if (remaining === 0) {
  console.log(0);
} else if (tail === 0) {
  console.log(-1);
} else {
  let days = 0;
  while (head < tail && remaining > 0) {
    const todayEnd = tail;
    while (head < todayEnd) {
      const position = queue[head++];
      const row = Math.floor(position / columns);
      const column = position % columns;
      if (row > 0) spread(position - columns);
      if (row + 1 < rows) spread(position + columns);
      if (column > 0) spread(position - 1);
      if (column + 1 < columns) spread(position + 1);
    }
    days += 1;
  }
  console.log(remaining === 0 ? days : -1);
}

function spread(position) {
  if (cells[position] === 0) {
    cells[position] = 1;
    remaining -= 1;
    queue[tail++] = position;
  }
}
