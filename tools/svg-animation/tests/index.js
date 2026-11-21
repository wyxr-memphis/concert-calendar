// Entry point so `node --test tools/svg-animation/tests` works on Node 22+, where a directory
// argument is resolved as a module (-> this file) instead of being scanned for test files.
import './easing.test.js';
import './interp.test.js';
import './presets.test.js';
import './timeline-math.test.js';
