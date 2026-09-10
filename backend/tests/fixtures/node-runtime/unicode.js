const fs = require('node:fs');

process.stdout.write(fs.readFileSync(0, 'utf8'));
