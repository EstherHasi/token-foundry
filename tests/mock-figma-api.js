// In-memory mock of the Figma Plugin variables API (Node and browser).
function mkFigma(exp) {
  let n = 1000;
  const cols = new Map();
  const vars = new Map();
  class Col {
    constructor(id, name, modes) { Object.assign(this, { id, name, modes, remote: false }); }
    get defaultModeId() { return this.modes[0].modeId; }
    get variableIds() { return [...vars.values()].filter((v) => v.variableCollectionId === this.id).map((v) => v.id); }
    renameMode(id, name) { this.modes.find((m) => m.modeId === id).name = name; }
    addMode(name) {
      if (this.modes.length >= 4) throw new Error("mode limit");
      const id = "m" + n++;
      this.modes.push({ modeId: id, name });
      return id;
    }
  }
  class Var {
    constructor(o) {
      Object.assign(this, o);
      this.codeSyntax = this.codeSyntax || {};
      this.scopes = this.scopes || ["ALL_SCOPES"];
      this.description = this.description || "";
    }
    setValueForMode(m, v) {
      if (v && v.type === "VARIABLE_ALIAS" && !vars.has(v.id)) throw new Error("alias target missing");
      this.valuesByMode[m] = JSON.parse(JSON.stringify(v));
    }
    setVariableCodeSyntax(p, s) { this.codeSyntax[p] = s; }
  }
  if (exp) {
    exp.collections.forEach((c) => cols.set(c.id, new Col(c.id, c.name, c.modes.map((m) => ({ ...m })))));
    exp.variables.forEach((v) => vars.set(v.id, new Var(JSON.parse(JSON.stringify(v)))));
  }
  return {
    root: { name: "Mock file" },
    variables: {
      getLocalVariableCollectionsAsync: async () => [...cols.values()],
      getLocalVariablesAsync: async () => [...vars.values()],
      getVariableByIdAsync: async (id) => vars.get(id) || null,
      createVariableCollection: (name) => {
        const id = "VariableCollectionId:n" + n++;
        const c = new Col(id, name, [{ modeId: "m" + n++, name: "Mode 1" }]);
        cols.set(id, c);
        return c;
      },
      createVariable: (name, col, type) => {
        const id = "VariableID:n" + n++;
        const v = new Var({ id, name, resolvedType: type, variableCollectionId: col.id, valuesByMode: {} });
        vars.set(id, v);
        return v;
      },
    },
  };
}
if (typeof module !== "undefined") module.exports = mkFigma;
