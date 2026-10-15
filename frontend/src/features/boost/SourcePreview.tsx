import { Collapse, Empty, Image, Tag, Typography } from "antd";
import type { SourceDocument, SourceItem, SourceTableCell } from "./types";

const { Text } = Typography;

function CellContent({ cell }: { cell: SourceTableCell }) {
  return (
    <>
      {cell.text.split("\n").map((line, index) => <div key={index}>{line}</div>)}
      {cell.images.map((image) => <Image key={image.id} src={image.url} width={Math.min(image.px_w, 220)} preview={{ mask: "预览" }} />)}
    </>
  );
}

function PreviewItem({ item, number }: { item: SourceItem; number?: string }) {
  switch (item.type) {
    case "heading":
      return <div className={`preview-heading level-${item.level}`}><span className="preview-number">{number}</span>{item.text}</div>;
    case "paragraph":
      return <p className={item.kind === "note" ? "preview-note" : "preview-paragraph"}>{item.kind === "note" && !item.text.startsWith("★") ? "★" : ""}{item.text}</p>;
    case "list": {
      const ListTag = item.style === "bullet" ? "ul" : "ol";
      return (
        <ListTag className={`preview-list ${item.style}`}>
          {item.items.map((entry, index) => <li key={index} className={entry.level ? "sub" : undefined}>{entry.text}</li>)}
        </ListTag>
      );
    }
    case "table":
      return (
        <div className="preview-table-wrap">
          <table className="preview-table">
            <tbody>
              {item.rows.map((row, rowIndex) => (
                <tr key={rowIndex} className={rowIndex < item.header_rows ? "header" : undefined}>
                  {row.map((cell) => (
                    <td key={cell.col} colSpan={cell.col_span} rowSpan={cell.row_span}><CellContent cell={cell} /></td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    case "image":
      return <div className="preview-image"><Image src={item.ref.url} width={Math.min(item.ref.px_w, 480)} preview={{ mask: "预览" }} /></div>;
  }
}

function numberItems(chapterNumber: number, items: SourceItem[]): (string | undefined)[] {
  let level3 = 0;
  let level4 = 0;
  return items.map((item) => {
    if (item.type !== "heading") return undefined;
    if (item.level === 3) {
      level3 += 1;
      level4 = 0;
      return `5.${chapterNumber}.${level3}`;
    }
    level4 += 1;
    return `5.${chapterNumber}.${level3}.${level4}`;
  });
}

export default function SourcePreview({ document }: { document: SourceDocument }) {
  if (!document.chapters.length) return <Empty description="没有可生成的章节" />;
  return (
    <div className="source-preview">
      <Collapse
        defaultActiveKey={["0"]}
        items={document.chapters.map((chapter, index) => {
          const chapterNumber = index + 2;
          const numbers = numberItems(chapterNumber, chapter.items);
          const tables = chapter.items.filter((item) => item.type === "table").length;
          return {
            key: String(index),
            label: <span className="preview-chapter">5.{chapterNumber} {chapter.title}</span>,
            extra: <Text type="secondary">{chapter.items.length} 项{tables ? ` · ${tables} 表` : ""}</Text>,
            children: chapter.items.length
              ? chapter.items.map((item, itemIndex) => <PreviewItem key={itemIndex} item={item} number={numbers[itemIndex]} />)
              : <Text type="secondary">此章节没有内容，只生成标题</Text>
          };
        })}
      />
      {document.revision_history.length > 0 && (
        <div className="preview-revisions">
          <Tag>版本修改记录</Tag>
          {document.revision_history.map((line, index) => <div key={index}>{line}</div>)}
        </div>
      )}
    </div>
  );
}
