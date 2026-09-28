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

const rows = Number(nextToken());
const columns = Number(nextToken());
const grid = new Array(rows);
for (let row = 0; row < rows; row += 1) grid[row] = nextToken();

const size = rows * columns;
const distances = new Int32Array(size);
const queue = new Int32Array(size);
let head = 0;
let tail = 1;
queue[0] = 0;
distances[0] = 1;

while (head < tail) {
  const position = queue[head++];
  if (position === size - 1) break;
  const row = Math.floor(position / columns);
  const column = position % columns;
  const nextDistance = distances[position] + 1;

  if (row > 0) visit(position - columns, row - 1, column, nextDistance);
  if (row + 1 < rows) visit(position + columns, row + 1, column, nextDistance);
  if (column > 0) visit(position - 1, row, column - 1, nextDistance);
  if (column + 1 < columns) visit(position + 1, row, column + 1, nextDistance);
}

console.log(distances[size - 1]);

function visit(position, row, column, distance) {
  if (distances[position] === 0 && grid[row][column] === "1") {
    distances[position] = distance;
    queue[tail++] = position;
  }
}
