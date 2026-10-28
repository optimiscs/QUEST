const fs = require('fs'), path = require('path'), assert = require('assert');
const root = path.join(__dirname, '..', 'web');
assert.equal(fs.realpathSync(path.join(root, 'trace-viewer/index.html')), fs.realpathSync(path.join(root, 'trace-viewer-zh/index.html')));
const app = fs.readFileSync(path.join(root, 'trace-viewer/app.js'), 'utf8');
assert(app.includes('window.location.pathname'));
console.log('language routes use one HTML entry');
