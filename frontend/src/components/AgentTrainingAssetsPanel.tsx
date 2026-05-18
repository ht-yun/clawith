import type { CSSProperties } from 'react';
import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
    IconBrain,
    IconBulb,
    IconPlus,
    IconSparkles,
    IconTrash,
    IconPencil,
    IconCheck,
    IconX,
} from '@tabler/icons-react';

import { useDialog } from './Dialog/DialogProvider';
import { useToast } from './Toast/ToastProvider';
import { agentTrainingApi, fetchJson } from '../services/api';

type MemoryPortrait = {
    id: string;
    title: string;
    category: string;
    content: string;
    priority: number;
    source_type: string;
    source_session_id?: string | null;
    is_active: boolean;
    created_at?: string | null;
    updated_at?: string | null;
};

type GoldenQuestion = {
    id: string;
    title: string;
    scenario: string;
    question_text: string;
    intent_tag: string;
    priority: number;
    source_type: string;
    source_session_id?: string | null;
    is_active: boolean;
    created_at?: string | null;
    updated_at?: string | null;
};

type SessionOption = {
    id: string;
    title: string;
    username?: string;
    source_channel?: string;
    last_message_at?: string | null;
};

type CandidateMemory = {
    title: string;
    category: string;
    content: string;
    priority: number;
    source_type: string;
    source_session_id?: string | null;
};

type CandidateQuestion = {
    title: string;
    scenario: string;
    question_text: string;
    intent_tag: string;
    priority: number;
    source_type: string;
    source_session_id?: string | null;
};

type EditorState =
    | { kind: 'memory'; mode: 'create' | 'edit'; item?: MemoryPortrait }
    | { kind: 'question'; mode: 'create' | 'edit'; item?: GoldenQuestion };

type DistillState =
    | { kind: 'memory' }
    | { kind: 'question' };

function cardStyle(): CSSProperties {
    return {
        border: '1px solid var(--border-subtle)',
        borderRadius: '10px',
        padding: '16px',
        background: 'var(--bg-secondary)',
        display: 'flex',
        flexDirection: 'column',
        gap: '12px',
    };
}

function badgeStyle(active: boolean): CSSProperties {
    return {
        display: 'inline-flex',
        alignItems: 'center',
        gap: '6px',
        borderRadius: '999px',
        padding: '2px 8px',
        fontSize: '11px',
        fontWeight: 600,
        background: active ? 'rgba(16,185,129,0.12)' : 'rgba(148,163,184,0.14)',
        color: active ? '#059669' : 'var(--text-secondary)',
    };
}

function formatWhen(value?: string | null) {
    if (!value) return '-';
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function AssetRow(props: {
    title: string;
    subtitle: string;
    body: string;
    priority: number;
    sourceType: string;
    updatedAt?: string | null;
    active: boolean;
    onEdit?: () => void;
    onDelete?: () => void;
}) {
    const { title, subtitle, body, priority, sourceType, updatedAt, active, onEdit, onDelete } = props;
    return (
        <div style={{ border: '1px solid var(--border-subtle)', borderRadius: '10px', padding: '12px', background: 'var(--bg-primary)', display: 'grid', gap: '8px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'flex-start' }}>
                <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)' }}>{title}</div>
                    <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                        {subtitle} - priority {priority} - {sourceType} - {formatWhen(updatedAt)}
                    </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
                    <span style={badgeStyle(active)}>{active ? 'Active' : 'Inactive'}</span>
                    {onEdit && <button className="btn btn-ghost" onClick={onEdit}><IconPencil size={14} stroke={1.8} /></button>}
                    {onDelete && <button className="btn btn-ghost" onClick={onDelete}><IconTrash size={14} stroke={1.8} /></button>}
                </div>
            </div>
            <div style={{ fontSize: '13px', color: 'var(--text-primary)', lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>{body}</div>
        </div>
    );
}

export default function AgentTrainingAssetsPanel({
    agentId,
    canManage,
    canViewAllSessions,
}: {
    agentId: string;
    canManage: boolean;
    canViewAllSessions: boolean;
}) {
    const dialog = useDialog();
    const toast = useToast();
    const queryClient = useQueryClient();

    const [editor, setEditor] = useState<EditorState | null>(null);
    const [distillState, setDistillState] = useState<DistillState | null>(null);
    const [memoryForm, setMemoryForm] = useState({
        title: '',
        category: 'user_preference',
        content: '',
        priority: 50,
        source_type: 'manual',
        source_session_id: '',
        is_active: true,
    });
    const [questionForm, setQuestionForm] = useState({
        title: '',
        scenario: 'requirements_unclear',
        question_text: '',
        intent_tag: 'missing_context',
        priority: 50,
        source_type: 'manual',
        source_session_id: '',
        is_active: true,
    });
    const [selectedSessionId, setSelectedSessionId] = useState('');
    const [maxItems, setMaxItems] = useState(5);
    const [memoryCandidates, setMemoryCandidates] = useState<CandidateMemory[]>([]);
    const [questionCandidates, setQuestionCandidates] = useState<CandidateQuestion[]>([]);
    const [adoptingKey, setAdoptingKey] = useState<string | null>(null);

    const { data: memoryPortraits = [], isLoading: memoryLoading } = useQuery({
        queryKey: ['training-memory-portraits', agentId],
        queryFn: () => agentTrainingApi.listMemoryPortraits(agentId) as Promise<MemoryPortrait[]>,
        enabled: !!agentId,
    });

    const { data: goldenQuestions = [], isLoading: goldenLoading } = useQuery({
        queryKey: ['training-golden-questions', agentId],
        queryFn: () => agentTrainingApi.listGoldenQuestions(agentId) as Promise<GoldenQuestion[]>,
        enabled: !!agentId,
    });

    const { data: sessionOptions = [] } = useQuery({
        queryKey: ['training-source-sessions', agentId, canViewAllSessions ? 'all' : 'mine'],
        queryFn: () => fetchJson<SessionOption[]>(`/agents/${agentId}/sessions?scope=${canViewAllSessions ? 'all' : 'mine'}`),
        enabled: !!agentId && !!distillState && canManage,
    });

    const invalidateAll = () => {
        queryClient.invalidateQueries({ queryKey: ['training-memory-portraits', agentId] });
        queryClient.invalidateQueries({ queryKey: ['training-golden-questions', agentId] });
    };

    const saveMemoryMut = useMutation({
        mutationFn: async () => {
            const payload = {
                ...memoryForm,
                source_session_id: memoryForm.source_session_id || null,
            };
            if (editor?.mode === 'edit' && editor.kind === 'memory' && editor.item) {
                return agentTrainingApi.updateMemoryPortrait(agentId, editor.item.id, payload);
            }
            return agentTrainingApi.createMemoryPortrait(agentId, payload);
        },
        onSuccess: () => {
            invalidateAll();
            setEditor(null);
            toast.success('Memory portrait saved');
        },
        onError: async (err: any) => {
            await dialog.alert('Failed to save memory portrait', { type: 'error', details: String(err?.message || err) });
        },
    });

    const saveQuestionMut = useMutation({
        mutationFn: async () => {
            const payload = {
                ...questionForm,
                source_session_id: questionForm.source_session_id || null,
            };
            if (editor?.mode === 'edit' && editor.kind === 'question' && editor.item) {
                return agentTrainingApi.updateGoldenQuestion(agentId, editor.item.id, payload);
            }
            return agentTrainingApi.createGoldenQuestion(agentId, payload);
        },
        onSuccess: () => {
            invalidateAll();
            setEditor(null);
            toast.success('Golden question saved');
        },
        onError: async (err: any) => {
            await dialog.alert('Failed to save golden question', { type: 'error', details: String(err?.message || err) });
        },
    });

    const distillMut = useMutation({
        mutationFn: async () => {
            if (!selectedSessionId) throw new Error('Please select a chat session first');
            if (distillState?.kind === 'memory') {
                return agentTrainingApi.distillMemoryPortraits(agentId, { chat_session_id: selectedSessionId, max_items: maxItems });
            }
            return agentTrainingApi.distillGoldenQuestions(agentId, { chat_session_id: selectedSessionId, max_items: maxItems });
        },
        onSuccess: (items: any[]) => {
            if (distillState?.kind === 'memory') setMemoryCandidates(items as CandidateMemory[]);
            else setQuestionCandidates(items as CandidateQuestion[]);
        },
        onError: async (err: any) => {
            await dialog.alert('Failed to distill candidates', { type: 'error', details: String(err?.message || err) });
        },
    });

    const openMemoryEditor = (item?: MemoryPortrait) => {
        setMemoryForm({
            title: item?.title || '',
            category: item?.category || 'user_preference',
            content: item?.content || '',
            priority: item?.priority ?? 50,
            source_type: item?.source_type || 'manual',
            source_session_id: item?.source_session_id || '',
            is_active: item?.is_active ?? true,
        });
        setEditor({ kind: 'memory', mode: item ? 'edit' : 'create', item });
    };

    const openQuestionEditor = (item?: GoldenQuestion) => {
        setQuestionForm({
            title: item?.title || '',
            scenario: item?.scenario || 'requirements_unclear',
            question_text: item?.question_text || '',
            intent_tag: item?.intent_tag || 'missing_context',
            priority: item?.priority ?? 50,
            source_type: item?.source_type || 'manual',
            source_session_id: item?.source_session_id || '',
            is_active: item?.is_active ?? true,
        });
        setEditor({ kind: 'question', mode: item ? 'edit' : 'create', item });
    };

    const removeMemory = async (item: MemoryPortrait) => {
        const ok = await dialog.confirm(`Delete memory portrait "${item.title}"?`, { danger: true });
        if (!ok) return;
        try {
            await agentTrainingApi.deleteMemoryPortrait(agentId, item.id);
            invalidateAll();
            toast.success('Memory portrait deleted');
        } catch (err: any) {
            await dialog.alert('Failed to delete memory portrait', { type: 'error', details: String(err?.message || err) });
        }
    };

    const removeQuestion = async (item: GoldenQuestion) => {
        const ok = await dialog.confirm(`Delete golden question "${item.title}"?`, { danger: true });
        if (!ok) return;
        try {
            await agentTrainingApi.deleteGoldenQuestion(agentId, item.id);
            invalidateAll();
            toast.success('Golden question deleted');
        } catch (err: any) {
            await dialog.alert('Failed to delete golden question', { type: 'error', details: String(err?.message || err) });
        }
    };

    const sessionLabel = useMemo(() => {
        const found = sessionOptions.find(s => s.id === selectedSessionId);
        return found ? `${found.title}${found.username ? ` - ${found.username}` : ''}` : '';
    }, [selectedSessionId, sessionOptions]);

    const adoptMemoryCandidate = async (candidate: CandidateMemory, idx: number) => {
        setAdoptingKey(`memory-${idx}`);
        try {
            await agentTrainingApi.createMemoryPortrait(agentId, { ...candidate, is_active: true });
            setMemoryCandidates(prev => prev.filter((_, i) => i !== idx));
            invalidateAll();
            toast.success('Memory portrait adopted');
        } catch (err: any) {
            await dialog.alert('Failed to adopt memory portrait candidate', { type: 'error', details: String(err?.message || err) });
        } finally {
            setAdoptingKey(null);
        }
    };

    const adoptQuestionCandidate = async (candidate: CandidateQuestion, idx: number) => {
        setAdoptingKey(`question-${idx}`);
        try {
            await agentTrainingApi.createGoldenQuestion(agentId, { ...candidate, is_active: true });
            setQuestionCandidates(prev => prev.filter((_, i) => i !== idx));
            invalidateAll();
            toast.success('Golden question adopted');
        } catch (err: any) {
            await dialog.alert('Failed to adopt golden question candidate', { type: 'error', details: String(err?.message || err) });
        } finally {
            setAdoptingKey(null);
        }
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            <div>
                <h3 style={{ marginBottom: '4px' }}>Training Assets</h3>
                <p style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginBottom: '12px' }}>
                    Agent-scoped training memory portraits and reusable clarifying questions. These assets are injected into runtime context without replacing the existing `memory/` files.
                </p>
            </div>

            <div style={{ display: 'grid', gap: '16px' }}>
                <div style={cardStyle()}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'flex-start' }}>
                        <div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '15px', fontWeight: 600 }}>
                                <IconBrain size={18} stroke={1.8} /> Memory Portrait
                            </div>
                            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '4px', lineHeight: 1.6 }}>
                                Durable user preference, communication, habit, and constraint cues for long-term alignment.
                            </div>
                        </div>
                        {canManage && (
                            <div style={{ display: 'flex', gap: '8px', flexShrink: 0 }}>
                                <button className="btn btn-secondary" onClick={() => { setDistillState({ kind: 'memory' }); setSelectedSessionId(''); setMemoryCandidates([]); setQuestionCandidates([]); }}>
                                    <IconSparkles size={14} stroke={1.8} /> Distill from Session
                                </button>
                                <button className="btn btn-primary" onClick={() => openMemoryEditor()}>
                                    <IconPlus size={14} stroke={1.8} /> New
                                </button>
                            </div>
                        )}
                    </div>
                    {memoryLoading ? (
                        <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>Loading memory portraits...</div>
                    ) : memoryPortraits.length === 0 ? (
                        <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>No memory portraits yet.</div>
                    ) : (
                        <div style={{ display: 'grid', gap: '10px' }}>
                            {memoryPortraits.map(item => (
                                <AssetRow
                                    key={item.id}
                                    title={item.title}
                                    subtitle={item.category}
                                    body={item.content}
                                    priority={item.priority}
                                    sourceType={item.source_type}
                                    updatedAt={item.updated_at}
                                    active={item.is_active}
                                    onEdit={canManage ? () => openMemoryEditor(item) : undefined}
                                    onDelete={canManage ? () => removeMemory(item) : undefined}
                                />
                            ))}
                        </div>
                    )}
                </div>

                <div style={cardStyle()}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'flex-start' }}>
                        <div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '15px', fontWeight: 600 }}>
                                <IconBulb size={18} stroke={1.8} /> Golden Questions
                            </div>
                            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '4px', lineHeight: 1.6 }}>
                                High-quality clarifying questions the agent should prefer when the user request is underspecified.
                            </div>
                        </div>
                        {canManage && (
                            <div style={{ display: 'flex', gap: '8px', flexShrink: 0 }}>
                                <button className="btn btn-secondary" onClick={() => { setDistillState({ kind: 'question' }); setSelectedSessionId(''); setMemoryCandidates([]); setQuestionCandidates([]); }}>
                                    <IconSparkles size={14} stroke={1.8} /> Distill from Session
                                </button>
                                <button className="btn btn-primary" onClick={() => openQuestionEditor()}>
                                    <IconPlus size={14} stroke={1.8} /> New
                                </button>
                            </div>
                        )}
                    </div>
                    {goldenLoading ? (
                        <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>Loading golden questions...</div>
                    ) : goldenQuestions.length === 0 ? (
                        <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>No golden questions yet.</div>
                    ) : (
                        <div style={{ display: 'grid', gap: '10px' }}>
                            {goldenQuestions.map(item => (
                                <AssetRow
                                    key={item.id}
                                    title={item.title}
                                    subtitle={`${item.scenario} - ${item.intent_tag}`}
                                    body={item.question_text}
                                    priority={item.priority}
                                    sourceType={item.source_type}
                                    updatedAt={item.updated_at}
                                    active={item.is_active}
                                    onEdit={canManage ? () => openQuestionEditor(item) : undefined}
                                    onDelete={canManage ? () => removeQuestion(item) : undefined}
                                />
                            ))}
                        </div>
                    )}
                </div>
            </div>

            {editor?.kind === 'memory' && (
                <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={() => setEditor(null)}>
                    <div onClick={e => e.stopPropagation()} style={{ background: 'var(--bg-primary)', borderRadius: '12px', padding: '24px', width: '92%', maxWidth: '720px', display: 'grid', gap: '12px', maxHeight: '85vh', overflowY: 'auto' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <h3 style={{ margin: 0 }}>{editor.mode === 'edit' ? 'Edit Memory Portrait' : 'New Memory Portrait'}</h3>
                            <button className="btn btn-ghost" onClick={() => setEditor(null)}><IconX size={16} stroke={1.8} /></button>
                        </div>
                        <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 0.8fr 120px', gap: '10px' }}>
                            <input className="input" placeholder="Title" value={memoryForm.title} onChange={e => setMemoryForm(prev => ({ ...prev, title: e.target.value }))} />
                            <input className="input" placeholder="Category" value={memoryForm.category} onChange={e => setMemoryForm(prev => ({ ...prev, category: e.target.value }))} />
                            <input className="input" type="number" placeholder="Priority" value={memoryForm.priority} onChange={e => setMemoryForm(prev => ({ ...prev, priority: Number(e.target.value || 0) }))} />
                        </div>
                        <textarea className="input" rows={5} placeholder="Reusable alignment cue" value={memoryForm.content} onChange={e => setMemoryForm(prev => ({ ...prev, content: e.target.value }))} style={{ resize: 'vertical', width: '100%', boxSizing: 'border-box' }} />
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
                            <input className="input" placeholder="Source type" value={memoryForm.source_type} onChange={e => setMemoryForm(prev => ({ ...prev, source_type: e.target.value }))} />
                            <input className="input" placeholder="Source session id (optional)" value={memoryForm.source_session_id} onChange={e => setMemoryForm(prev => ({ ...prev, source_session_id: e.target.value }))} />
                        </div>
                        <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', color: 'var(--text-secondary)' }}>
                            <input type="checkbox" checked={memoryForm.is_active} onChange={e => setMemoryForm(prev => ({ ...prev, is_active: e.target.checked }))} />
                            Active in runtime context
                        </label>
                        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                            <button className="btn btn-secondary" onClick={() => setEditor(null)}>Cancel</button>
                            <button className="btn btn-primary" disabled={!memoryForm.title.trim() || !memoryForm.content.trim() || saveMemoryMut.isPending} onClick={() => saveMemoryMut.mutate()}>
                                {saveMemoryMut.isPending ? 'Saving...' : 'Save'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {editor?.kind === 'question' && (
                <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={() => setEditor(null)}>
                    <div onClick={e => e.stopPropagation()} style={{ background: 'var(--bg-primary)', borderRadius: '12px', padding: '24px', width: '92%', maxWidth: '720px', display: 'grid', gap: '12px', maxHeight: '85vh', overflowY: 'auto' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <h3 style={{ margin: 0 }}>{editor.mode === 'edit' ? 'Edit Golden Question' : 'New Golden Question'}</h3>
                            <button className="btn btn-ghost" onClick={() => setEditor(null)}><IconX size={16} stroke={1.8} /></button>
                        </div>
                        <div style={{ display: 'grid', gridTemplateColumns: '1.1fr 0.9fr 120px', gap: '10px' }}>
                            <input className="input" placeholder="Title" value={questionForm.title} onChange={e => setQuestionForm(prev => ({ ...prev, title: e.target.value }))} />
                            <input className="input" placeholder="Scenario" value={questionForm.scenario} onChange={e => setQuestionForm(prev => ({ ...prev, scenario: e.target.value }))} />
                            <input className="input" type="number" placeholder="Priority" value={questionForm.priority} onChange={e => setQuestionForm(prev => ({ ...prev, priority: Number(e.target.value || 0) }))} />
                        </div>
                        <input className="input" placeholder="Intent tag" value={questionForm.intent_tag} onChange={e => setQuestionForm(prev => ({ ...prev, intent_tag: e.target.value }))} />
                        <textarea className="input" rows={5} placeholder="Clarifying question text" value={questionForm.question_text} onChange={e => setQuestionForm(prev => ({ ...prev, question_text: e.target.value }))} style={{ resize: 'vertical', width: '100%', boxSizing: 'border-box' }} />
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
                            <input className="input" placeholder="Source type" value={questionForm.source_type} onChange={e => setQuestionForm(prev => ({ ...prev, source_type: e.target.value }))} />
                            <input className="input" placeholder="Source session id (optional)" value={questionForm.source_session_id} onChange={e => setQuestionForm(prev => ({ ...prev, source_session_id: e.target.value }))} />
                        </div>
                        <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', color: 'var(--text-secondary)' }}>
                            <input type="checkbox" checked={questionForm.is_active} onChange={e => setQuestionForm(prev => ({ ...prev, is_active: e.target.checked }))} />
                            Active in runtime context
                        </label>
                        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                            <button className="btn btn-secondary" onClick={() => setEditor(null)}>Cancel</button>
                            <button className="btn btn-primary" disabled={!questionForm.title.trim() || !questionForm.question_text.trim() || saveQuestionMut.isPending} onClick={() => saveQuestionMut.mutate()}>
                                {saveQuestionMut.isPending ? 'Saving...' : 'Save'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {distillState && (
                <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }} onClick={() => setDistillState(null)}>
                    <div onClick={e => e.stopPropagation()} style={{ background: 'var(--bg-primary)', borderRadius: '12px', padding: '24px', width: '92%', maxWidth: '860px', display: 'grid', gap: '14px', maxHeight: '88vh', overflowY: 'auto' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <h3 style={{ margin: 0 }}>{distillState.kind === 'memory' ? 'Distill Memory Portrait Candidates' : 'Distill Golden Question Candidates'}</h3>
                            <button className="btn btn-ghost" onClick={() => setDistillState(null)}><IconX size={16} stroke={1.8} /></button>
                        </div>
                        <p style={{ margin: 0, fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
                            Choose a chat session, generate draft candidates, then adopt the ones worth keeping as long-term training assets.
                        </p>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 120px auto', gap: '10px', alignItems: 'center' }}>
                            <select className="input" value={selectedSessionId} onChange={e => setSelectedSessionId(e.target.value)}>
                                <option value="">Select a chat session</option>
                                {sessionOptions.map(session => (
                                    <option key={session.id} value={session.id}>
                                        {session.title}{session.username ? ` - ${session.username}` : ''}{session.source_channel ? ` - ${session.source_channel}` : ''}
                                    </option>
                                ))}
                            </select>
                            <input className="input" type="number" min={1} max={20} value={maxItems} onChange={e => setMaxItems(Math.max(1, Math.min(20, Number(e.target.value || 1))))} />
                            <button className="btn btn-primary" disabled={!selectedSessionId || distillMut.isPending} onClick={() => distillMut.mutate()}>
                                {distillMut.isPending ? 'Distilling...' : 'Generate'}
                            </button>
                        </div>
                        {sessionLabel && (
                            <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Source session: {sessionLabel}</div>
                        )}

                        {distillState.kind === 'memory' && (
                            <div style={{ display: 'grid', gap: '10px' }}>
                                {memoryCandidates.length === 0 ? (
                                    <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>No candidates yet.</div>
                                ) : memoryCandidates.map((item, idx) => (
                                    <div key={`${item.title}-${idx}`} style={{ border: '1px solid var(--border-subtle)', borderRadius: '10px', padding: '12px', background: 'var(--bg-secondary)', display: 'grid', gap: '8px' }}>
                                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px' }}>
                                            <div>
                                                <div style={{ fontWeight: 600, fontSize: '14px' }}>{item.title}</div>
                                                <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>{item.category} - priority {item.priority}</div>
                                            </div>
                                            <button className="btn btn-primary" disabled={adoptingKey === `memory-${idx}`} onClick={() => adoptMemoryCandidate(item, idx)}>
                                                <IconCheck size={14} stroke={1.8} /> {adoptingKey === `memory-${idx}` ? 'Adopting...' : 'Adopt'}
                                            </button>
                                        </div>
                                        <div style={{ fontSize: '13px', lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>{item.content}</div>
                                    </div>
                                ))}
                            </div>
                        )}

                        {distillState.kind === 'question' && (
                            <div style={{ display: 'grid', gap: '10px' }}>
                                {questionCandidates.length === 0 ? (
                                    <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>No candidates yet.</div>
                                ) : questionCandidates.map((item, idx) => (
                                    <div key={`${item.title}-${idx}`} style={{ border: '1px solid var(--border-subtle)', borderRadius: '10px', padding: '12px', background: 'var(--bg-secondary)', display: 'grid', gap: '8px' }}>
                                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px' }}>
                                            <div>
                                                <div style={{ fontWeight: 600, fontSize: '14px' }}>{item.title}</div>
                                                <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>{item.scenario} - {item.intent_tag} - priority {item.priority}</div>
                                            </div>
                                            <button className="btn btn-primary" disabled={adoptingKey === `question-${idx}`} onClick={() => adoptQuestionCandidate(item, idx)}>
                                                <IconCheck size={14} stroke={1.8} /> {adoptingKey === `question-${idx}` ? 'Adopting...' : 'Adopt'}
                                            </button>
                                        </div>
                                        <div style={{ fontSize: '13px', lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>{item.question_text}</div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}
