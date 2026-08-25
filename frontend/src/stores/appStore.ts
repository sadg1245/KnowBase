import { create } from 'zustand';
import {
  Workspace,
  Document,
  LLMSettings,
  getWorkspaces,
  getDocuments,
  getLLMSettings,
} from '../services/api';

interface AppState {
  currentWorkspace: Workspace | null;
  workspaces: Workspace[];
  documents: Document[];
  settings: LLMSettings | null;
  loading: boolean;

  fetchWorkspaces: () => Promise<void>;
  setCurrentWorkspace: (workspace: Workspace | null) => void;
  fetchDocuments: (workspaceId: string) => Promise<void>;
  fetchSettings: () => Promise<void>;
}

export const useAppStore = create<AppState>((set) => ({
  currentWorkspace: null,
  workspaces: [],
  documents: [],
  settings: null,
  loading: false,

  fetchWorkspaces: async () => {
    set({ loading: true });
    try {
      const workspaces = await getWorkspaces();
      set({ workspaces, loading: false });
    } catch {
      set({ loading: false });
    }
  },

  setCurrentWorkspace: (workspace) => {
    set({ currentWorkspace: workspace });
  },

  fetchDocuments: async (workspaceId: string) => {
    set({ loading: true });
    try {
      const documents = await getDocuments(workspaceId);
      set({ documents, loading: false });
    } catch {
      set({ loading: false });
    }
  },

  fetchSettings: async () => {
    try {
      const settings = await getLLMSettings();
      set({ settings });
    } catch {
      // 忽略错误
    }
  },
}));
