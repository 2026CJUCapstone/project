const fs = require('node:fs');

const numbers = fs.readFileSync(0, 'utf8').trim().split(/\s+/).map(Number);
console.log(numbers.reduce((total, value) => total + value, 0));
