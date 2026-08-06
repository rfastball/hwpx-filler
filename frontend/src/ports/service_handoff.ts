import { createHandoffPort } from "../screens/ports.ts";

export type NeedsSheetPayload = Record<string, unknown>;
export type DataMountDescriptor = Record<string, unknown>;

export type SheetPickerPort = {
  choose(
    screen: string,
    payload: NeedsSheetPayload,
  ): Promise<DataMountDescriptor | `ERROR:${string}` | null>;
};

export type RelinkNotify = (message: string, kind?: "ok" | "cancel" | "error") => void;
export type RelinkPort = {
  relinkTemplate(screen: string, name: string, notify?: RelinkNotify): Promise<boolean>;
};

export function createServiceHandoffPorts() {
  return {
    sheetPicker: createHandoffPort<SheetPickerPort>("SheetPickerPort"),
    relink: createHandoffPort<RelinkPort>("RelinkPort"),
  };
}

export type ServiceHandoffPorts = ReturnType<typeof createServiceHandoffPorts>;
