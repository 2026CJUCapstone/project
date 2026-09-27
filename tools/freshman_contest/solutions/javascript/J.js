"use strict";

const fs = require("fs");
const input = fs.readFileSync(0, "utf8");
let inputIndex = 0;

function nextToken() {
  while (inputIndex < input.length && input.charCodeAt(inputIndex) <= 32) inputIndex += 1;
  const start = inputIndex;
  while (inputIndex < input.length && input.charCodeAt(inputIndex) > 32) inputIndex += 1;
  return input.slice(start, inputIndex);
}

class Fenwick {
  constructor(size) {
    this.tree = new Int32Array(size + 1);
  }

  add(index) {
    for (index += 1; index < this.tree.length; index += index & -index) this.tree[index] += 1;
  }

  before(index) {
    let count = 0;
    for (; index > 0; index -= index & -index) count += this.tree[index];
    return count;
  }
}

function compareBigInt(left, right) {
  if (left < right) return -1;
  if (left > right) return 1;
  return 0;
}

function uniqueSorted(values) {
  values.sort(compareBigInt);
  const unique = [];
  for (const value of values) {
    if (unique.length === 0 || unique[unique.length - 1] !== value) unique.push(value);
  }
  return unique;
}

function lowerBound(values, target) {
  let low = 0;
  let high = values.length;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (values[middle] < target) low = middle + 1;
    else high = middle;
  }
  return low;
}

function nonnegativeRemainder(value, divisor) {
  const remainder = value % divisor;
  return remainder < 0n ? remainder + divisor : remainder;
}

const count = Number(nextToken());
const prefixes = new Array(count);
let total = 0n;
for (let index = 0; index < count; index += 1) {
  prefixes[index] = total;
  total += BigInt(nextToken());
}

const remainders = uniqueSorted(prefixes.map((value) => nonnegativeRemainder(value, total)));
const sortedPrefixes = [...prefixes].sort(compareBigInt);
const remainderCounts = new Fenwick(remainders.length);
let quotientSum = 0n;
let answer = 0n;

for (let index = 0; index < count; index += 1) {
  const value = sortedPrefixes[index];
  const remainder = nonnegativeRemainder(value, total);
  // Subtracting the nonnegative remainder makes this dividend divisible by
  // total, so BigInt's truncation is equal to mathematical floor division.
  const quotient = (value - remainder) / total;
  const rank = lowerBound(remainders, remainder);
  answer += BigInt(index) * quotient - quotientSum + BigInt(remainderCounts.before(rank));
  quotientSum += quotient;
  remainderCounts.add(rank);
}

const prefixValues = uniqueSorted([...prefixes]);
const increasingCounts = new Fenwick(prefixValues.length);
for (const value of prefixes) {
  const rank = lowerBound(prefixValues, value);
  answer -= BigInt(increasingCounts.before(rank));
  increasingCounts.add(rank);
}

console.log(answer.toString());
