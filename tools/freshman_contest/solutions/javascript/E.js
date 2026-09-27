"use strict";

const fs = require("fs");
const input = fs.readFileSync(0, "utf8");
const counts = new Int32Array(26);

for (let index = 0; index < input.length; index += 1) {
  let code = input.charCodeAt(index);
  if (code >= 97 && code <= 122) code -= 32;
  if (code >= 65 && code <= 90) counts[code - 65] += 1;
}

let winner = 0;
let tied = false;
for (let letter = 1; letter < 26; letter += 1) {
  if (counts[letter] > counts[winner]) {
    winner = letter;
    tied = false;
  } else if (counts[letter] === counts[winner]) {
    tied = true;
  }
}
console.log(tied ? "?" : String.fromCharCode(65 + winner));
