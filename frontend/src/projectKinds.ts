export type BusinessKind = "cabinet" | "boost";
export type DocumentKind = "report" | "plan";
export const BUSINESSES: { value: BusinessKind; label: string; documents: DocumentKind[] }[] = [
  { value: "cabinet", label: "工商业柜", documents: ["report", "plan"] },
  { value: "boost", label: "升压一体机", documents: ["plan"] }
];
export const DOCUMENTS: { value: DocumentKind; label: string }[] = [
  { value: "report", label: "测试报告" }, { value: "plan", label: "测试方案" }
];
