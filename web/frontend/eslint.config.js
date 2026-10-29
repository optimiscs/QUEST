import globals from 'globals';
export default [{
  files: ['src/**/*.js'],
  languageOptions: { globals: globals.browser, ecmaVersion: 2022, sourceType: 'module' },
  rules: { 'no-undef': 'error', 'no-unreachable': 'error', 'no-dupe-keys': 'error' },
}];
