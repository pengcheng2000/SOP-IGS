import { DeleteOutlined, HolderOutlined } from "@ant-design/icons";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Button, Input, Tag } from "antd";
import type { Photo } from "../../types";

export default function SortablePhoto({
  photo,
  onCaption,
  onDelete
}: {
  photo: Photo;
  onCaption: (value: string) => void;
  onDelete: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: photo.id });
  return (
    <div
      ref={setNodeRef}
      className={`photo-card ${isDragging ? "dragging" : ""}`}
      style={{ transform: CSS.Transform.toString(transform), transition }}
    >
      <div className="photo-preview">
        {photo.status === "processed" ? (
          <img src={photo.preview_url} alt={photo.caption || photo.original_filename} />
        ) : (
          <div className="photo-error"><Tag color="error">处理失败</Tag></div>
        )}
        <button className="drag-handle" aria-label="拖动调整照片顺序" {...attributes} {...listeners}>
          <HolderOutlined />
        </button>
      </div>
      <div className="photo-meta">
        <Input
          defaultValue={photo.caption}
          maxLength={200}
          placeholder="可选照片说明"
          onBlur={(event) => onCaption(event.target.value)}
        />
        <Button type="text" danger icon={<DeleteOutlined />} aria-label="删除照片" onClick={onDelete} />
      </div>
    </div>
  );
}

