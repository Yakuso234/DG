import type { Metadata } from "next";
import { FlowPilotWorkbench } from "./workbench";

export const metadata: Metadata = {
  title: "FlowPilot Workbench",
  description: "Local enterprise ticket-resolution agent workbench",
};

export default function FlowPilotPage() {
  return <FlowPilotWorkbench />;
}
