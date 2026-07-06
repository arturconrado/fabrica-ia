export type Dict = Record<string, any>;

export type RunBundle = {
  run: Dict | null;
  nodes: Dict[];
  events: Dict[];
  artifacts: Dict[];
  files: Dict[];
  diffs: Dict[];
  tests: Dict[];
  requirements: Dict[];
  criteria: Dict[];
  traceability: Dict[];
  gates: Dict[];
  homologation: Dict;
  feedback: Dict[];
  agentStates: Dict[];
  agentMessages: Dict[];
  workItems: Dict[];
};
