const domMock = { append: () => {} };
const documentMock = { createElement: () => ({ dataset: {}, append: () => {} }) };

const state = { projects: [{slug: 'test', name: 'Test Project'}] };
const comps = [{
  title: 'Test',
  project: 'test',
  area_m2: 50,
  bedrooms: 2,
  similarity_score: 0.9
}];

const textCell = (val) => val;
const formatArea = (val) => val;
const formatComparablePrice = (comp, purpose) => purpose;
const mapCell = (comp) => comp;
const purpose = "sale";

try {
  comps.forEach((comp, index) => {
    const row = documentMock.createElement("tr");
    row.dataset.compIndex = String(index);
    const prj = state.projects?.find(p => p.slug === comp.project);
    const projectName = prj ? prj.name : comp.project;
    
    row.append(
      textCell(comp.title || "Tin chưa có tiêu đề"),
      textCell(projectName || "-"),
      textCell(formatArea(comp.area_m2)),
      textCell(comp.bedrooms ?? "-"),
      textCell(formatComparablePrice(comp, purpose)),
      textCell(`${Math.round((comp.similarity_score || 0) * 100)}%`),
      mapCell(comp)
    );
    domMock.append(row);
  });
  console.log("Success");
} catch(e) {
  console.error("Error:", e);
}
