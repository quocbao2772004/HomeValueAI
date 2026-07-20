const fs = require('fs');
const code = fs.readFileSync('frontend/app.js', 'utf8');

// Mock DOM
const { JSDOM } = require("jsdom");
const dom = new JSDOM(`<!DOCTYPE html><html><body>
  <tbody id="compRows"></tbody>
  <select id="mapCompSelect"></select>
</body></html>`);
global.document = dom.window.document;
global.window = dom.window;
global.state = { projects: [{slug: "vop", name: "Vinhomes Ocean Park"}], mapComps: [] };
global.formatArea = () => "50 m2";
global.formatComparablePrice = () => "2 ty";
global.mapCell = () => document.createElement("td");
global.$ = id => document.getElementById(id);
global.refreshIcons = () => {};

// Evaluate code
eval(code);

// Test
const comps = [{title: "Test", project: "vop", area_m2: 50, bedrooms: 2, similarity_score: 0.9, source_url: "url"}];
try {
  renderComps(comps, "sale");
  console.log("Success! Output HTML:", document.getElementById("compRows").innerHTML);
} catch (e) {
  console.error("Error:", e);
}
