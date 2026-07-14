import type { ReactNode } from "react";
import {
  TextField,
  Input,
  TextArea,
  Label,
  Description,
  FieldError,
  NumberField,
  Select,
  ListBox,
  Switch,
  Checkbox,
} from "@heroui/react";

/* ---------- layout helpers ---------- */

export function FieldGrid({ children }: { children: ReactNode }) {
  return <div className="grid gap-4 sm:grid-cols-2">{children}</div>;
}

export function FormCard({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-border bg-surface/50 p-5">
      <div className="mb-4">
        <h2 className="font-display text-lg font-medium text-foreground">{title}</h2>
        {description && <p className="mt-0.5 text-sm text-muted">{description}</p>}
      </div>
      <div className="flex flex-col gap-4">{children}</div>
    </section>
  );
}

/* ---------- text input ---------- */

export function TextInput({
  label,
  value,
  onChange,
  placeholder,
  hint,
  error,
  type = "text",
  isRequired,
  isDisabled,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  hint?: string;
  error?: string;
  type?: "text" | "email" | "password" | "url" | "date" | "datetime-local" | "time";
  isRequired?: boolean;
  isDisabled?: boolean;
}) {
  return (
    <TextField
      value={value}
      onChange={onChange}
      isInvalid={!!error}
      isRequired={isRequired}
      isDisabled={isDisabled}
      className="flex flex-col gap-1"
    >
      <Label className="text-sm font-medium text-foreground">{label}</Label>
      <Input placeholder={placeholder} type={type} />
      {hint && <Description className="text-xs text-muted">{hint}</Description>}
      {error && <FieldError className="text-xs text-danger">{error}</FieldError>}
    </TextField>
  );
}

/* ---------- textarea ---------- */

export function TextAreaInput({
  label,
  value,
  onChange,
  placeholder,
  hint,
  rows = 4,
  isDisabled,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  hint?: string;
  rows?: number;
  isDisabled?: boolean;
}) {
  return (
    <TextField
      value={value}
      onChange={onChange}
      isDisabled={isDisabled}
      className="flex flex-col gap-1"
    >
      <Label className="text-sm font-medium text-foreground">{label}</Label>
      <TextArea rows={rows} placeholder={placeholder} />
      {hint && <Description className="text-xs text-muted">{hint}</Description>}
    </TextField>
  );
}

/* ---------- number ---------- */

export function NumberInput({
  label,
  value,
  onChange,
  min,
  max,
  step,
  hint,
  isDisabled,
}: {
  label: string;
  value: number | undefined;
  onChange: (v: number | undefined) => void;
  min?: number;
  max?: number;
  step?: number;
  hint?: string;
  isDisabled?: boolean;
}) {
  return (
    <NumberField
      value={value ?? Number.NaN}
      onChange={(v) => onChange(Number.isNaN(v) ? undefined : v)}
      minValue={min}
      maxValue={max}
      step={step}
      isDisabled={isDisabled}
      className="flex flex-col gap-1"
    >
      <Label className="text-sm font-medium text-foreground">{label}</Label>
      <NumberField.Group>
        <NumberField.DecrementButton />
        <NumberField.Input />
        <NumberField.IncrementButton />
      </NumberField.Group>
      {hint && <Description className="text-xs text-muted">{hint}</Description>}
    </NumberField>
  );
}

/* ---------- select ---------- */

export interface Option {
  value: string;
  label: string;
}

export function SelectInput({
  label,
  value,
  onChange,
  options,
  placeholder = "Select…",
  hint,
  isDisabled,
}: {
  label?: string;
  value: string | undefined;
  onChange: (v: string) => void;
  options: Option[];
  placeholder?: string;
  hint?: string;
  isDisabled?: boolean;
}) {
  return (
    <Select
      selectedKey={value ?? null}
      onSelectionChange={(k) => onChange(String(k))}
      placeholder={placeholder}
      isDisabled={isDisabled}
      className="flex flex-col gap-1"
    >
      {label && <Label className="text-sm font-medium text-foreground">{label}</Label>}
      <Select.Trigger>
        <Select.Value />
        <Select.Indicator />
      </Select.Trigger>
      {hint && <Description className="text-xs text-muted">{hint}</Description>}
      <Select.Popover>
        <ListBox>
          {options.map((o) => (
            <ListBox.Item key={o.value} id={o.value} textValue={o.label}>
              {o.label}
            </ListBox.Item>
          ))}
        </ListBox>
      </Select.Popover>
    </Select>
  );
}

/* ---------- switch ---------- */

export function SwitchInput({
  label,
  value,
  onChange,
  hint,
  isDisabled,
}: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
  hint?: string;
  isDisabled?: boolean;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <Switch isSelected={value} onChange={onChange} isDisabled={isDisabled}>
        <Switch.Content>
          <Switch.Control>
            <Switch.Thumb />
          </Switch.Control>
          <span className="text-sm font-medium text-foreground">{label}</span>
        </Switch.Content>
      </Switch>
      {hint && <p className="ps-1 text-xs text-muted">{hint}</p>}
    </div>
  );
}

/* ---------- checkbox ---------- */

export function CheckboxInput({
  label,
  value,
  onChange,
  isDisabled,
}: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
  isDisabled?: boolean;
}) {
  return (
    <Checkbox isSelected={value} onChange={onChange} isDisabled={isDisabled}>
      <Checkbox.Content>
        <Checkbox.Control>
          <Checkbox.Indicator />
        </Checkbox.Control>
        <span className="text-sm text-foreground">{label}</span>
      </Checkbox.Content>
    </Checkbox>
  );
}

/* ---------- comma / chip tags editor ---------- */

export function TagsInput({
  label,
  value,
  onChange,
  hint,
  placeholder = "Comma-separated values",
}: {
  label: string;
  value: string[];
  onChange: (v: string[]) => void;
  hint?: string;
  placeholder?: string;
}) {
  return (
    <TextField
      value={value.join(", ")}
      onChange={(raw) =>
        onChange(
          raw
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean),
        )
      }
      className="flex flex-col gap-1"
    >
      <Label className="text-sm font-medium text-foreground">{label}</Label>
      <Input placeholder={placeholder} />
      <Description className="text-xs text-muted">
        {hint ?? "Separate items with commas."}
      </Description>
    </TextField>
  );
}
