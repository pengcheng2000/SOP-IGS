import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  CloudUploadOutlined,
  DeleteOutlined,
  EditOutlined,
  PlusOutlined
} from "@ant-design/icons";
import { DndContext, PointerSensor, useDroppable, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { SortableContext, arrayMove, rectSortingStrategy } from "@dnd-kit/sortable";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App as AntApp, Button, Card, Empty, Input, Modal, Progress, Space, Tag, Typography } from "antd";
import { useMemo, useRef, useState } from "react";
import { api, uploadWithProgress } from "../../api";
import type { Photo, PhotoGroup, Project, TreeItem } from "../../types";
import SortablePhoto from "./SortablePhoto";

const { Title, Text } = Typography;

type UploadProgress = {
  id: string;
  name: string;
  percent: number;
  stage: "uploading" | "processing" | "failed";
  error?: string;
};

const requirementLabels = {
  required: { color: "error", text: "必填" },
  recommended: { color: "warning", text: "推荐" },
  optional: { color: "default", text: "可选" }
} as const;

function PhotoGroupCard({
  group,
  photos,
  uploads,
  onFiles,
  onCaption,
  onDeletePhoto,
  onRename,
  onDeleteGroup,
  onMoveGroup
}: {
  group: PhotoGroup;
  photos: Photo[];
  uploads: UploadProgress[];
  onFiles: (files: File[]) => void;
  onCaption: (photo: Photo, value: string) => void;
  onDeletePhoto: (photo: Photo) => void;
  onRename: () => void;
  onDeleteGroup: () => void;
  onMoveGroup: (direction: -1 | 1) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const { setNodeRef, isOver } = useDroppable({ id: group.id });
  const requirement = requirementLabels[group.requiredness];
  return (
    <div ref={setNodeRef} className={`photo-group-card ${isOver ? "drop-target" : ""}`}>
      <div className="photo-group-head">
        <div>
          <Space wrap>
            <Title level={5}>{group.title}</Title>
            <Tag color={requirement.color}>{requirement.text}{group.min_photos ? ` ≥ ${group.min_photos} 张` : ""}</Tag>
            <Tag>{group.source === "template" ? "模板分组" : "自定义"}</Tag>
          </Space>
          {group.hint && <Text type="secondary">{group.hint}</Text>}
        </div>
        {group.source === "custom" && (
          <Space>
            <Button type="text" icon={<ArrowUpOutlined />} aria-label="分组上移" onClick={() => onMoveGroup(-1)} />
            <Button type="text" icon={<ArrowDownOutlined />} aria-label="分组下移" onClick={() => onMoveGroup(1)} />
            <Button type="text" icon={<EditOutlined />} onClick={onRename}>重命名</Button>
            <Button type="text" danger icon={<DeleteOutlined />} onClick={onDeleteGroup}>删除分组</Button>
          </Space>
        )}
      </div>
      <div
        className="photo-dropzone"
        onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "copy"; }}
        onDrop={(event) => {
          event.preventDefault();
          onFiles([...event.dataTransfer.files]);
        }}
        onClick={() => inputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") inputRef.current?.click(); }}
      >
        <CloudUploadOutlined />
        <div><Text strong>拖拽照片到此处，或点击选择</Text><br /><Text type="secondary">JPG、PNG、HEIC；每张最大 30 MB</Text></div>
        <input
          ref={inputRef}
          hidden
          type="file"
          multiple
          accept="image/jpeg,image/png,image/heic,image/heif,.heic,.heif"
          onChange={(event) => {
            onFiles([...(event.target.files ?? [])]);
            event.currentTarget.value = "";
          }}
        />
      </div>
      {uploads.map((upload) => (
        <div className="upload-progress" key={upload.id}>
          <div><Text>{upload.name}</Text><Text type={upload.stage === "failed" ? "danger" : "secondary"}>{upload.stage === "uploading" ? "上传中" : upload.stage === "processing" ? "服务器正在解析、旋转和压缩" : upload.error}</Text></div>
          <Progress percent={upload.percent} status={upload.stage === "failed" ? "exception" : upload.stage === "processing" ? "active" : "normal"} size="small" />
        </div>
      ))}
      {photos.length ? (
        <SortableContext items={photos.map((photo) => photo.id)} strategy={rectSortingStrategy}>
          <div className="photo-grid">
            {photos.map((photo) => (
              <SortablePhoto
                key={photo.id}
                photo={photo}
                onCaption={(value) => onCaption(photo, value)}
                onDelete={() => onDeletePhoto(photo)}
              />
            ))}
          </div>
        </SortableContext>
      ) : <div className="photo-group-empty">当前分组还没有照片</div>}
    </div>
  );
}

export default function PhotoWorkspace({
  project,
  leafItems
}: {
  project: Project;
  leafItems: TreeItem[];
}) {
  const { message, modal } = AntApp.useApp();
  const queryClient = useQueryClient();
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 5 } }));
  const [uploads, setUploads] = useState<Record<string, UploadProgress>>({});
  const [groupDialog, setGroupDialog] = useState<{ testItemId: string; group?: PhotoGroup }>();
  const [groupTitle, setGroupTitle] = useState("");
  const groupsQuery = useQuery({
    queryKey: ["photo-groups", project.id],
    queryFn: () => api<PhotoGroup[]>(`/api/projects/${project.id}/photo-groups`)
  });
  const photosQuery = useQuery({
    queryKey: ["photos", project.id],
    queryFn: () => api<Photo[]>(`/api/projects/${project.id}/photos`)
  });
  const groups = groupsQuery.data ?? [];
  const photos = photosQuery.data ?? [];
  const photosByGroup = useMemo(() => {
    const result = new Map<string, Photo[]>();
    photos.forEach((photo) => result.set(photo.photo_group_id, [...(result.get(photo.photo_group_id) ?? []), photo]));
    result.forEach((items) => items.sort((left, right) => left.sort_order - right.sort_order));
    return result;
  }, [photos]);
  const groupById = useMemo(() => new Map(groups.map((group) => [group.id, group])), [groups]);
  const photoById = useMemo(() => new Map(photos.map((photo) => [photo.id, photo])), [photos]);

  async function refresh() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["photo-groups", project.id] }),
      queryClient.invalidateQueries({ queryKey: ["photos", project.id] }),
      queryClient.invalidateQueries({ queryKey: ["preflight", project.id] })
    ]);
  }

  async function uploadOne(group: PhotoGroup, file: File) {
    const id = `${group.id}:${file.name}:${file.lastModified}:${crypto.randomUUID()}`;
    setUploads((current) => ({ ...current, [id]: { id, name: file.name, percent: 0, stage: "uploading" } }));
    const data = new FormData();
    data.set("photo_group_id", group.id);
    data.append("files", file);
    try {
      const result = await uploadWithProgress<Photo[]>(
        `/api/projects/${project.id}/photos`,
        data,
        (percent, stage) => setUploads((current) => ({ ...current, [id]: { ...current[id], percent, stage } }))
      );
      const failure = result.find((photo) => photo.status === "failed");
      if (failure) throw new Error(failure.error_detail || failure.error_code || "图片处理失败");
      setUploads((current) => { const next = { ...current }; delete next[id]; return next; });
    } catch (error) {
      setUploads((current) => ({ ...current, [id]: { ...current[id], percent: 100, stage: "failed", error: error instanceof Error ? error.message : "上传失败" } }));
    }
  }

  async function uploadFiles(group: PhotoGroup, files: File[]) {
    if (!files.length) return;
    let cursor = 0;
    const workers = Array.from({ length: Math.min(3, files.length) }, async () => {
      while (cursor < files.length) {
        const file = files[cursor++];
        await uploadOne(group, file);
      }
    });
    await Promise.all(workers);
    await refresh();
  }

  async function dragEnd(event: DragEndEvent) {
    if (!event.over || event.active.id === event.over.id) return;
    const active = photoById.get(String(event.active.id));
    if (!active) return;
    const overPhoto = photoById.get(String(event.over.id));
    const targetGroupId = overPhoto?.photo_group_id ?? (groupById.has(String(event.over.id)) ? String(event.over.id) : undefined);
    if (!targetGroupId) return;
    if (targetGroupId !== active.photo_group_id) {
      try {
        await api(`/api/photos/${active.id}`, { method: "PATCH", body: JSON.stringify({ photo_group_id: targetGroupId }) });
        await refresh();
      } catch (error) { message.error(error instanceof Error ? error.message : "移动失败"); }
      return;
    }
    const items = photosByGroup.get(active.photo_group_id) ?? [];
    const oldIndex = items.findIndex((item) => item.id === active.id);
    const newIndex = items.findIndex((item) => item.id === String(event.over?.id));
    if (oldIndex < 0 || newIndex < 0) return;
    const next = arrayMove(items, oldIndex, newIndex);
    try {
      await api(`/api/photo-groups/${active.photo_group_id}/order`, { method: "PUT", body: JSON.stringify({ photo_ids: next.map((item) => item.id) }) });
      await refresh();
    } catch (error) { message.error(error instanceof Error ? error.message : "排序失败"); }
  }

  async function updateCaption(photo: Photo, value: string) {
    if (value === photo.caption) return;
    await api(`/api/photos/${photo.id}`, { method: "PATCH", body: JSON.stringify({ caption: value }) });
    queryClient.invalidateQueries({ queryKey: ["photos", project.id] });
  }

  async function deletePhoto(photo: Photo) {
    await api(`/api/photos/${photo.id}`, { method: "DELETE" });
    await refresh();
  }

  const saveGroup = useMutation({
    mutationFn: () => groupDialog?.group
      ? api(`/api/photo-groups/${groupDialog.group.id}`, { method: "PATCH", body: JSON.stringify({ title: groupTitle }) })
      : api(`/api/projects/${project.id}/photo-groups`, { method: "POST", body: JSON.stringify({ test_item_id: groupDialog?.testItemId, title: groupTitle }) }),
    onSuccess: async () => { setGroupDialog(undefined); setGroupTitle(""); await refresh(); },
    onError: (error) => message.error(error.message)
  });

  function deleteGroup(group: PhotoGroup) {
    modal.confirm({
      title: `删除分组“${group.title}”？`,
      content: "只有空的自定义分组可以删除。",
      okButtonProps: { danger: true },
      onOk: async () => {
        await api(`/api/photo-groups/${group.id}`, { method: "DELETE" });
        await refresh();
      }
    });
  }

  async function moveGroup(itemGroups: PhotoGroup[], group: PhotoGroup, direction: -1 | 1) {
    const custom = itemGroups.filter((item) => item.source === "custom");
    const index = custom.findIndex((item) => item.id === group.id);
    const target = index + direction;
    if (index < 0 || target < 0 || target >= custom.length) return;
    const reordered = arrayMove(custom, index, target);
    try {
      await api(`/api/projects/${project.id}/photo-groups/order`, {
        method: "PUT",
        body: JSON.stringify({ photo_group_ids: reordered.map((item) => item.id) })
      });
      await refresh();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "分组排序失败");
    }
  }

  return (
    <DndContext sensors={sensors} onDragEnd={dragEnd}>
      <div className="photo-sections">
        <Card className="workspace-card photo-section" bordered={false}>
          <div className="section-heading">
            <div><Title level={4}>4.3 样品照片</Title><Text type="secondary">建议包含正面关门、正面开门和两张对角 45° 照片。缺图确认后仍可生成。</Text></div>
          </div>
          <div className="photo-groups">
            {groups.filter((group) => group.scope === "sample").sort((a, b) => a.sort_order - b.sort_order).map((group) => (
              <PhotoGroupCard key={group.id} group={group} photos={photosByGroup.get(group.id) ?? []}
                uploads={Object.values(uploads).filter((upload) => upload.id.startsWith(`${group.id}:`))}
                onFiles={(files) => uploadFiles(group, files)} onCaption={updateCaption} onDeletePhoto={deletePhoto}
                onRename={() => undefined} onDeleteGroup={() => undefined} onMoveGroup={() => undefined} />
            ))}
          </div>
        </Card>
        {leafItems.map((item) => {
          const itemGroups = groups
            .filter((group) => group.test_item_id === item.id)
            .sort((left, right) => (left.source === right.source ? left.sort_order - right.sort_order : left.source === "template" ? -1 : 1));
          return (
            <Card className="workspace-card photo-section" bordered={false} key={item.id}>
              <div className="section-heading">
                <div><Title level={4}>{project.display_numbers[item.id]} {item.title}</Title><Text type="secondary">照片按分组分别排版，不会跨分类混排。</Text></div>
                <Button icon={<PlusOutlined />} onClick={() => { setGroupDialog({ testItemId: item.id }); setGroupTitle(""); }}>新增自定义分组</Button>
              </div>
              <div className="photo-groups">
                {itemGroups.map((group) => (
                  <PhotoGroupCard
                    key={group.id}
                    group={group}
                    photos={photosByGroup.get(group.id) ?? []}
                    uploads={Object.values(uploads).filter((upload) => upload.id.startsWith(`${group.id}:`))}
                    onFiles={(files) => uploadFiles(group, files)}
                    onCaption={updateCaption}
                    onDeletePhoto={deletePhoto}
                    onRename={() => { setGroupDialog({ testItemId: item.id, group }); setGroupTitle(group.title); }}
                    onDeleteGroup={() => deleteGroup(group)}
                    onMoveGroup={(direction) => moveGroup(itemGroups, group, direction)}
                  />
                ))}
              </div>
            </Card>
          );
        })}
        {!leafItems.length && <Empty description="请先选择测试项目" />}
      </div>
      <Modal
        title={groupDialog?.group ? "重命名自定义分组" : "新增自定义分组"}
        open={Boolean(groupDialog)}
        onCancel={() => setGroupDialog(undefined)}
        onOk={() => saveGroup.mutate()}
        confirmLoading={saveGroup.isPending}
        okButtonProps={{ disabled: !groupTitle.trim() }}
      >
        <Input value={groupTitle} maxLength={100} placeholder="例如：测试后状态" onChange={(event) => setGroupTitle(event.target.value)} />
      </Modal>
    </DndContext>
  );
}
