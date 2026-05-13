import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { agentApi } from '../services/api';
import LinearCopyButton from '../components/LinearCopyButton';

function fetchAuth<T>(url: string, options?: RequestInit): Promise<T> {
    const token = localStorage.getItem('token');
    return fetch(`/api${url}`, {
        ...options,
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    }).then(r => r.json());
}

interface OpenCodeSettingsProps {
    agent: any;
    agentId: string;
}

export default function OpenCodeSettings({ agent, agentId }: OpenCodeSettingsProps) {
    const { t, i18n } = useTranslation();
    const queryClient = useQueryClient();
    const navigate = useNavigate();
    const isChinese = i18n.language?.startsWith('zh');

    // ─── Node management state ───────────────────────────
    const { data: nodes = [], isLoading } = useQuery<any[]>({
        queryKey: ['agent-nodes', agentId],
        queryFn: () => agentApi.listNodes(agentId),
        enabled: !!agentId,
        refetchInterval: 30000, // Auto-refresh every 30s for status updates
    });

    const [newKey, setNewKey] = useState<string | null>(null);
    const [newKeyNodeId, setNewKeyNodeId] = useState<string | null>(null);
    const [creating, setCreating] = useState(false);
    const [creatingName, setCreatingName] = useState('');
    const [showCreateInput, setShowCreateInput] = useState(false);
    const [regeneratingNodeId, setRegeneratingNodeId] = useState<string | null>(null);
    const [showRegenConfirm, setShowRegenConfirm] = useState<string | null>(null);
    const [deletingNodeId, setDeletingNodeId] = useState<string | null>(null);
    const [showDeleteConfirm, setShowDeleteConfirm] = useState<string | null>(null);

    // ─── Deletion ────────────────────────────────────────
    const [showAgentDeleteConfirm, setShowAgentDeleteConfirm] = useState(false);
    const [agentDeleting, setAgentDeleting] = useState(false);

    // ─── Permissions state ──────────────────────────────
    const { data: permData } = useQuery({
        queryKey: ['agent-permissions', agentId],
        queryFn: () => fetchAuth<any>(`/agents/${agentId}/permissions`),
        enabled: !!agentId,
    });

    // ─── Create node ─────────────────────────────────────
    const handleCreateNode = async () => {
        setCreating(true);
        try {
            const result = await agentApi.createNode(agentId, { node_name: creatingName || '' });
            setNewKeyNodeId(result.id);
            setNewKey(result.api_key);
            setCreatingName('');
            setShowCreateInput(false);
            queryClient.invalidateQueries({ queryKey: ['agent-nodes', agentId] });
            queryClient.invalidateQueries({ queryKey: ['agent', agentId] });
        } catch (e) {
            console.error('Failed to create node', e);
        } finally {
            setCreating(false);
        }
    };

    // ─── Regenerate key ─────────────────────────────────
    const handleRegenerateKey = async (nodeId: string) => {
        setRegeneratingNodeId(nodeId);
        try {
            const result = await agentApi.regenerateNodeKey(agentId, nodeId);
            setNewKeyNodeId(nodeId);
            setNewKey(result.api_key);
            setShowRegenConfirm(null);
            queryClient.invalidateQueries({ queryKey: ['agent-nodes', agentId] });
        } catch (e) {
            console.error('Failed to regenerate key', e);
        } finally {
            setRegeneratingNodeId(null);
        }
    };

    // ─── Delete node ────────────────────────────────────
    const handleDeleteNode = async (nodeId: string) => {
        setDeletingNodeId(nodeId);
        try {
            await agentApi.deleteNode(agentId, nodeId);
            setShowDeleteConfirm(null);
            queryClient.invalidateQueries({ queryKey: ['agent-nodes', agentId] });
            queryClient.invalidateQueries({ queryKey: ['agent', agentId] });
        } catch (e) {
            console.error('Failed to delete node', e);
        } finally {
            setDeletingNodeId(null);
        }
    };

    // ─── Delete agent ────────────────────────────────────
    const handleAgentDelete = async () => {
        setAgentDeleting(true);
        try {
            await agentApi.delete(agentId);
            queryClient.invalidateQueries({ queryKey: ['agents'] });
            navigate('/');
        } catch (e) {
            console.error('Failed to delete agent', e);
            setAgentDeleting(false);
        }
    };

    // ─── Permissions ────────────────────────────────────
    const handleScopeChange = async (newScope: string) => {
        try {
            await fetchAuth(`/agents/${agentId}/permissions`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ scope_type: newScope, scope_ids: [], access_level: permData?.access_level || 'use' }),
            });
            queryClient.invalidateQueries({ queryKey: ['agent-permissions', agentId] });
            queryClient.invalidateQueries({ queryKey: ['agent', agentId] });
        } catch (e) {
            console.error('Failed to update permissions', e);
        }
    };

    const handleAccessLevelChange = async (newLevel: string) => {
        try {
            await fetchAuth(`/agents/${agentId}/permissions`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ scope_type: permData?.scope_type || 'company', scope_ids: permData?.scope_ids || [], access_level: newLevel }),
            });
            queryClient.invalidateQueries({ queryKey: ['agent-permissions', agentId] });
            queryClient.invalidateQueries({ queryKey: ['agent', agentId] });
        } catch (e) {
            console.error('Failed to update access level', e);
        }
    };

    const isOwner = permData?.is_owner ?? false;
    const currentScope = permData?.scope_type || 'company';
    const currentAccessLevel = permData?.access_level || 'use';

    const getStatusBadge = (node: any) => {
        const isOnline = node.last_seen && (Date.now() - new Date(node.last_seen).getTime()) < 300_000;
        const color = isOnline ? '#22c55e' : '#9ca3af';
        const label = isOnline
            ? (isChinese ? '在线' : 'Online')
            : (isChinese ? '离线' : 'Offline');
        return (
            <span style={{
                fontSize: '11px', padding: '2px 8px', borderRadius: '10px',
                background: `${color}18`, color, fontWeight: 600,
                display: 'inline-flex', alignItems: 'center', gap: '4px',
            }}>
                <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: color, display: 'inline-block' }} />
                {label}
            </span>
        );
    };

    return (
        <div>
            <h3 style={{ marginBottom: '16px' }}>{t('agent.settings.title')}</h3>

            {/* ── Node List ── */}
            <div className="card" style={{ marginBottom: '12px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                    <div>
                        <h4 style={{ marginBottom: '2px' }}>
                            {isChinese ? 'OpenCode 节点' : 'OpenCode Nodes'}
                        </h4>
                        <p style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>
                            {isChinese
                                ? '每个节点拥有独立的 API Key，不同用户可各自部署 OpenCode 连接到此 Agent。'
                                : 'Each node has its own API Key. Different users can deploy their own OpenCode instances connected to this agent.'}
                        </p>
                    </div>
                    <button
                        className="btn btn-primary"
                        onClick={() => setShowCreateInput(true)}
                        disabled={showCreateInput}
                        style={{ padding: '5px 14px', fontSize: '12px', whiteSpace: 'nowrap' }}
                    >
                        + {isChinese ? '添加节点' : 'Add Node'}
                    </button>
                </div>

                {/* Create input */}
                {showCreateInput && (
                    <div style={{
                        display: 'flex', gap: '8px', marginBottom: '12px',
                        padding: '12px', borderRadius: '8px',
                        background: 'rgba(99,102,241,0.04)', border: '1px solid var(--border-subtle)',
                    }}>
                        <input
                            type="text"
                            value={creatingName}
                            onChange={e => setCreatingName(e.target.value)}
                            onKeyDown={e => e.key === 'Enter' && handleCreateNode()}
                            placeholder={isChinese ? '节点名称（如：我的MacBook）' : 'Node name (e.g. My MacBook)'}
                            style={{
                                flex: 1, padding: '6px 10px', borderRadius: '6px', border: '1px solid var(--border-subtle)',
                                fontSize: '13px', background: 'var(--bg-input)', color: 'var(--text-primary)',
                            }}
                            autoFocus
                        />
                        <button
                            className="btn btn-primary"
                            onClick={handleCreateNode}
                            disabled={creating}
                            style={{ padding: '6px 14px', fontSize: '12px', whiteSpace: 'nowrap' }}
                        >
                            {creating ? (isChinese ? '创建中...' : 'Creating...') : (isChinese ? '创建' : 'Create')}
                        </button>
                        <button
                            className="btn btn-secondary"
                            onClick={() => setShowCreateInput(false)}
                            style={{ padding: '6px 12px', fontSize: '12px' }}
                        >
                            {isChinese ? '取消' : 'Cancel'}
                        </button>
                    </div>
                )}

                {/* Node table */}
                {isLoading ? (
                    <div style={{ padding: '20px', textAlign: 'center', color: 'var(--text-tertiary)' }}>
                        {isChinese ? '加载中...' : 'Loading...'}
                    </div>
                ) : nodes.length === 0 ? (
                    <div style={{
                        padding: '24px', textAlign: 'center', color: 'var(--text-tertiary)',
                        border: '1px dashed var(--border-subtle)', borderRadius: '8px', fontSize: '13px',
                    }}>
                        {isChinese ? '暂无节点，点击上方按钮添加。' : 'No nodes yet. Click the button above to add one.'}
                    </div>
                ) : (
                    <div style={{ overflowX: 'auto' }}>
                        <table style={{ width: '100%', fontSize: '13px', borderCollapse: 'collapse' }}>
                            <thead>
                                <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                                    <th style={{ textAlign: 'left', padding: '8px 10px', color: 'var(--text-tertiary)', fontWeight: 500, fontSize: '11px' }}>
                                        {isChinese ? '节点名称' : 'Node Name'}
                                    </th>
                                    <th style={{ textAlign: 'left', padding: '8px 10px', color: 'var(--text-tertiary)', fontWeight: 500, fontSize: '11px' }}>
                                        {isChinese ? '状态' : 'Status'}
                                    </th>
                                    <th style={{ textAlign: 'left', padding: '8px 10px', color: 'var(--text-tertiary)', fontWeight: 500, fontSize: '11px' }}>
                                        {isChinese ? '最近心跳' : 'Last Seen'}
                                    </th>
                                    <th style={{ textAlign: 'right', padding: '8px 10px', color: 'var(--text-tertiary)', fontWeight: 500, fontSize: '11px' }}>
                                        {isChinese ? '操作' : 'Actions'}
                                    </th>
                                </tr>
                            </thead>
                            <tbody>
                                {nodes.map((node: any) => (
                                    <React.Fragment key={node.id}>
                                        <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                                            <td style={{ padding: '10px' }}>
                                                <div style={{ fontWeight: 500 }}>{node.node_name || 'Default'}</div>
                                                {node.owner_username && (
                                                    <div style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>
                                                        {node.owner_username}
                                                    </div>
                                                )}
                                            </td>
                                            <td style={{ padding: '10px' }}>
                                                {getStatusBadge(node)}
                                            </td>
                                            <td style={{ padding: '10px', color: 'var(--text-secondary)', fontSize: '12px' }}>
                                                {node.last_seen
                                                    ? new Date(node.last_seen).toLocaleString()
                                                    : (isChinese ? '从未' : 'Never')}
                                            </td>
                                            <td style={{ padding: '10px', textAlign: 'right' }}>
                                                <div style={{ display: 'flex', gap: '6px', justifyContent: 'flex-end' }}>
                                                    <button
                                                        className="btn btn-secondary"
                                                        onClick={() => setShowRegenConfirm(node.id)}
                                                        disabled={regeneratingNodeId === node.id}
                                                        style={{ padding: '3px 10px', fontSize: '11px' }}
                                                    >
                                                        {isChinese ? '重新生成' : 'Regen Key'}
                                                    </button>
                                                    <button
                                                        className="btn btn-danger"
                                                        onClick={() => setShowDeleteConfirm(node.id)}
                                                        disabled={deletingNodeId === node.id}
                                                        style={{ padding: '3px 10px', fontSize: '11px' }}
                                                    >
                                                        {isChinese ? '删除' : 'Delete'}
                                                    </button>
                                                </div>
                                            </td>
                                        </tr>

                                        {/* New key display */}
                                        {newKey && newKeyNodeId === node.id && (
                                            <tr>
                                                <td colSpan={4} style={{ padding: '8px 10px' }}>
                                                    <div style={{
                                                        display: 'flex', alignItems: 'center', gap: '8px',
                                                        padding: '10px 14px', background: 'rgba(99,102,241,0.06)',
                                                        borderRadius: '8px', border: '1px solid var(--accent-primary)',
                                                    }}>
                                                        <code style={{
                                                            flex: 1, fontSize: '12px', fontFamily: 'monospace',
                                                            wordBreak: 'break-all', color: 'var(--text-primary)',
                                                        }}>
                                                            {newKey}
                                                        </code>
                                                        <LinearCopyButton
                                                            className="btn btn-secondary"
                                                            textToCopy={newKey}
                                                            label="Copy"
                                                            copiedLabel="Copied"
                                                            style={{ padding: '4px 10px', fontSize: '11px', whiteSpace: 'nowrap' }}
                                                        />
                                                        <span style={{ fontSize: '11px', color: 'var(--error)' }}>
                                                            {isChinese ? '仅显示一次' : 'Shown only once'}
                                                        </span>
                                                    </div>
                                                </td>
                                            </tr>
                                        )}

                                        {/* Regen confirmation */}
                                        {showRegenConfirm === node.id && (
                                            <tr>
                                                <td colSpan={4} style={{ padding: '8px 10px' }}>
                                                    <div style={{
                                                        padding: '10px 14px', borderRadius: '8px',
                                                        background: 'rgba(255,180,80,0.06)', border: '1px solid rgba(255,180,80,0.2)',
                                                        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                                                    }}>
                                                        <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                                                            {isChinese
                                                                ? '确认重新生成？旧 Key 将立即失效。'
                                                                : 'Regenerate key? Old key will be revoked immediately.'}
                                                        </span>
                                                        <div style={{ display: 'flex', gap: '6px' }}>
                                                            <button
                                                                className="btn btn-secondary"
                                                                onClick={() => setShowRegenConfirm(null)}
                                                                style={{ padding: '3px 10px', fontSize: '11px' }}
                                                            >
                                                                {isChinese ? '取消' : 'Cancel'}
                                                            </button>
                                                            <button
                                                                className="btn btn-primary"
                                                                onClick={() => handleRegenerateKey(node.id)}
                                                                style={{ padding: '3px 10px', fontSize: '11px' }}
                                                            >
                                                                {isChinese ? '确认' : 'Confirm'}
                                                            </button>
                                                        </div>
                                                    </div>
                                                </td>
                                            </tr>
                                        )}

                                        {/* Delete confirmation */}
                                        {showDeleteConfirm === node.id && (
                                            <tr>
                                                <td colSpan={4} style={{ padding: '8px 10px' }}>
                                                    <div style={{
                                                        padding: '10px 14px', borderRadius: '8px',
                                                        background: 'rgba(255,80,80,0.06)', border: '1px solid rgba(255,80,80,0.2)',
                                                        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                                                    }}>
                                                        <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                                                            {isChinese
                                                                ? `确认删除节点 "${node.node_name || 'Default'}"？此操作不可逆。`
                                                                : `Delete node "${node.node_name || 'Default'}"? This cannot be undone.`}
                                                        </span>
                                                        <div style={{ display: 'flex', gap: '6px' }}>
                                                            <button
                                                                className="btn btn-secondary"
                                                                onClick={() => setShowDeleteConfirm(null)}
                                                                style={{ padding: '3px 10px', fontSize: '11px' }}
                                                            >
                                                                {isChinese ? '取消' : 'Cancel'}
                                                            </button>
                                                            <button
                                                                className="btn btn-danger"
                                                                onClick={() => handleDeleteNode(node.id)}
                                                                disabled={deletingNodeId === node.id}
                                                                style={{ padding: '3px 10px', fontSize: '11px' }}
                                                            >
                                                                {deletingNodeId === node.id ? '...' : (isChinese ? '确认删除' : 'Delete')}
                                                            </button>
                                                        </div>
                                                    </div>
                                                </td>
                                            </tr>
                                        )}
                                    </React.Fragment>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>

            {/* ── Permissions ── */}
            <div className="card" style={{ marginBottom: '12px' }}>
                <h4 style={{ marginBottom: '12px' }}>
                    {t('agent.settings.perm.title', 'Access Permissions')}
                </h4>
                <p style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginBottom: '16px' }}>
                    {t('agent.settings.perm.description', 'Control who can see and interact with this agent. Only the creator or admin can change this.')}
                </p>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginBottom: '16px' }}>
                    {(['company', 'user'] as const).map((scope) => (
                        <label
                            key={scope}
                            style={{
                                display: 'flex', alignItems: 'center', gap: '10px',
                                padding: '12px 14px', borderRadius: '8px',
                                cursor: isOwner ? 'pointer' : 'default',
                                border: currentScope === scope
                                    ? '1px solid var(--accent-primary)'
                                    : '1px solid var(--border-subtle)',
                                background: currentScope === scope
                                    ? 'rgba(99,102,241,0.06)'
                                    : 'transparent',
                                opacity: isOwner ? 1 : 0.7,
                                transition: 'all 0.15s',
                            }}
                        >
                            <input
                                type="radio"
                                name="perm_scope_oc"
                                checked={currentScope === scope}
                                disabled={!isOwner}
                                onChange={() => handleScopeChange(scope)}
                                style={{ accentColor: 'var(--accent-primary)' }}
                            />
                            <div>
                                <div style={{ fontWeight: 500, fontSize: '13px' }}>
                                    {scope === 'company'
                                        ? t('agent.settings.perm.companyWide', 'Company-wide')
                                        : t('agent.settings.perm.onlyMe', 'Only Me')}
                                </div>
                                <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '2px' }}>
                                    {scope === 'company' && t('agent.settings.perm.companyWideDesc', 'All users in the organization can use this agent')}
                                    {scope === 'user' && t('agent.settings.perm.onlyMeDesc', 'Only the creator can use this agent')}
                                </div>
                            </div>
                        </label>
                    ))}
                </div>

                {currentScope === 'company' && isOwner && (
                    <div style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: '12px' }}>
                        <label style={{ display: 'block', fontSize: '13px', fontWeight: 500, marginBottom: '8px' }}>
                            {t('agent.settings.perm.defaultAccess', 'Default Access Level')}
                        </label>
                        <div style={{ display: 'flex', gap: '8px' }}>
                            {[
                                { val: 'use', label: t('agent.settings.perm.useAccess', 'Use'), desc: t('agent.settings.perm.useAccessDesc', 'Task, Chat, Tools, Skills, Workspace') },
                                { val: 'manage', label: t('agent.settings.perm.manageAccess', 'Manage'), desc: t('agent.settings.perm.manageAccessDesc', 'Full access including Settings, Mind, Relationships') },
                            ].map(opt => (
                                <label key={opt.val}
                                    style={{
                                        flex: 1, padding: '10px 12px', borderRadius: '8px',
                                        cursor: 'pointer',
                                        border: currentAccessLevel === opt.val
                                            ? '1px solid var(--accent-primary)'
                                            : '1px solid var(--border-subtle)',
                                        background: currentAccessLevel === opt.val
                                            ? 'rgba(99,102,241,0.06)'
                                            : 'transparent',
                                        transition: 'all 0.15s',
                                    }}
                                >
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                        <input type="radio" name="access_level_oc" checked={currentAccessLevel === opt.val}
                                            onChange={() => handleAccessLevelChange(opt.val)}
                                            style={{ accentColor: 'var(--accent-primary)' }} />
                                        <span style={{ fontWeight: 500, fontSize: '13px' }}>{opt.label}</span>
                                    </div>
                                    <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '4px', marginLeft: '20px' }}>{opt.desc}</div>
                                </label>
                            ))}
                        </div>
                    </div>
                )}

                {currentScope !== 'company' && permData?.scope_names?.length > 0 && (
                    <div style={{ marginTop: '12px', fontSize: '12px', color: 'var(--text-secondary)' }}>
                        <span style={{ fontWeight: 500 }}>{t('agent.settings.perm.currentAccess', 'Current access')}:</span>{' '}
                        {permData.scope_names.map((s: any) => s.name).join(', ')}
                    </div>
                )}

                {!isOwner && (
                    <div style={{ marginTop: '12px', fontSize: '11px', color: 'var(--text-tertiary)', fontStyle: 'italic' }}>
                        {t('agent.settings.perm.readOnly', 'Only the creator or admin can change permissions')}
                    </div>
                )}
            </div>

            {/* ── Danger Zone ── */}
            {isOwner && (
                <div className="card" style={{
                    marginBottom: '12px',
                    border: '1px solid rgba(255,80,80,0.2)',
                }}>
                    <h4 style={{ marginBottom: '4px', color: 'var(--error)' }}>
                        {isChinese ? '危险操作' : 'Danger Zone'}
                    </h4>
                    <p style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginBottom: '12px' }}>
                        {isChinese
                            ? '删除后无法恢复，所有节点、聊天记录、活动日志和关联数据都将被永久清除。'
                            : 'This action cannot be undone. All nodes, chat history, activity logs, and associated data will be permanently deleted.'}
                    </p>

                    {showAgentDeleteConfirm ? (
                        <div style={{
                            padding: '14px', borderRadius: '8px',
                            background: 'rgba(255,80,80,0.06)', border: '1px solid rgba(255,80,80,0.2)',
                        }}>
                            <div style={{ fontSize: '13px', fontWeight: 500, marginBottom: '8px', color: 'var(--text-primary)' }}>
                                {isChinese
                                    ? `确认删除 Agent "${agent?.name}"？`
                                    : `Delete agent "${agent?.name}"?`}
                            </div>
                            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '12px' }}>
                                {isChinese
                                    ? '此操作不可撤销。'
                                    : 'This action is irreversible.'}
                            </div>
                            <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                                <button
                                    className="btn btn-secondary"
                                    onClick={() => setShowAgentDeleteConfirm(false)}
                                    style={{ padding: '5px 14px', fontSize: '12px' }}
                                >
                                    {isChinese ? '取消' : 'Cancel'}
                                </button>
                                <button
                                    className="btn btn-danger"
                                    onClick={handleAgentDelete}
                                    disabled={agentDeleting}
                                    style={{ padding: '5px 14px', fontSize: '12px' }}
                                >
                                    {agentDeleting
                                        ? (isChinese ? '删除中...' : 'Deleting...')
                                        : (isChinese ? '确认删除' : 'Delete')}
                                </button>
                            </div>
                        </div>
                    ) : (
                        <button
                            className="btn btn-danger"
                            onClick={() => setShowAgentDeleteConfirm(true)}
                            style={{ padding: '6px 20px', fontSize: '12px' }}
                        >
                            {isChinese ? '删除此 Agent' : 'Delete this Agent'}
                        </button>
                    )}
                </div>
            )}
        </div>
    );
}
