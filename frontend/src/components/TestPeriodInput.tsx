import { CalendarOutlined } from "@ant-design/icons";
import { Button, DatePicker, Input, Space } from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useState } from "react";

const DATE_FORMAT = "YYYY-MM-DD";

function parsePeriod(value?: string): [Dayjs, Dayjs] | null {
  const dates = value?.match(/\d{4}-\d{2}-\d{2}/g)?.map((text) => dayjs(text, DATE_FORMAT));
  if (!dates?.length || dates.some((date) => !date.isValid())) return null;
  return [dates[0], dates[dates.length - 1]];
}

function formatPeriod(start: Dayjs, end: Dayjs): string {
  return start.isSame(end, "day") ? start.format(DATE_FORMAT) : `${start.format(DATE_FORMAT)} 至 ${end.format(DATE_FORMAT)}`;
}

/** Free-text test period with a date-range picker button; used as a Form.Item control. */
export default function TestPeriodInput({ value, onChange }: { value?: string; onChange?: (value: string) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ position: "relative" }}>
      <Space.Compact style={{ width: "100%" }}>
        <Input value={value} placeholder="2026-09-01 至 2026-09-05" onChange={(event) => onChange?.(event.target.value)} />
        <Button icon={<CalendarOutlined />} onClick={() => setOpen((current) => !current)}>选择时间</Button>
      </Space.Compact>
      {/* Invisible anchor so the calendar popup opens under the input row. */}
      <DatePicker.RangePicker
        open={open}
        value={parsePeriod(value)}
        format={DATE_FORMAT}
        onOpenChange={setOpen}
        onChange={(dates) => {
          if (dates?.[0] && dates[1]) onChange?.(formatPeriod(dates[0], dates[1]));
          setOpen(false);
        }}
        style={{ position: "absolute", left: 0, top: 0, width: "100%", height: "100%", opacity: 0, pointerEvents: "none" }}
        tabIndex={-1}
      />
    </div>
  );
}
