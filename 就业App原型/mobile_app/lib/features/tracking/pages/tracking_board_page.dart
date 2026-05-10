import 'package:flutter/material.dart';

import '../../../core/network/api_client.dart';
import '../../../shared/models/job_tracking_item.dart';
import '../../../shared/models/job_tracking_summary.dart';
import 'import_job_page.dart';

class TrackingBoardPage extends StatefulWidget {
  const TrackingBoardPage({this.embedded = false, this.refreshToken = 0, super.key});

  final bool embedded;
  final int refreshToken;

  @override
  State<TrackingBoardPage> createState() => _TrackingBoardPageState();
}

class _TrackingBoardPageState extends State<TrackingBoardPage> {
  final ApiClient _apiClient = ApiClient();

  bool _loading = true;
  bool _updating = false;
  String? _error;
  List<JobTrackingItem> _items = const [];
  JobTrackingSummary _summary = const JobTrackingSummary(
    saved: 0, applied: 0, interview: 0, offer: 0, accepted: 0, rejected: 0,
  );

  static const _statusGroups = ['saved', 'applied', 'interview', 'offer', 'accepted', 'rejected'];
  static const _statusLabel = {
    'saved': '待投递', 'applied': '已投递', 'interview': '面试中',
    'offer': '已获Offer', 'accepted': '已录用', 'rejected': '已拒绝',
  };
  static const _statusIcon = {
    'saved': Icons.bookmark_outline, 'applied': Icons.send_outlined,
    'interview': Icons.people_outline, 'offer': Icons.card_giftcard_outlined,
    'accepted': Icons.check_circle_outline, 'rejected': Icons.cancel_outlined,
  };
  static const _statusColor = {
    'saved': Colors.grey, 'applied': Colors.blue, 'interview': Colors.orange,
    'offer': Colors.purple, 'accepted': Colors.green, 'rejected': Colors.red,
  };

  @override
  void initState() {
    super.initState();
    _loadTracking();
  }

  @override
  void didUpdateWidget(covariant TrackingBoardPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.refreshToken != oldWidget.refreshToken) {
      _loadTracking();
    }
  }

  Future<void> _loadTracking() async {
    setState(() { _loading = true; _error = null; });
    try {
      final result = await _apiClient.fetchTracking();
      if (!mounted) return;
      setState(() {
        _items = result['items'] as List<JobTrackingItem>;
        _summary = result['summary'] as JobTrackingSummary;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() { _error = error.toString(); });
    } finally {
      if (mounted) setState(() { _loading = false; });
    }
  }

  Future<void> _updateStatus(JobTrackingItem item, String newStatus) async {
    setState(() => _updating = true);
    try {
      await _apiClient.updateTracking(jobId: item.jobId, trackingStatus: newStatus);
      await _loadTracking();
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('更新失败: $error')),
        );
      }
    } finally {
      if (mounted) setState(() => _updating = false);
    }
  }

  Future<void> _deleteTracking(JobTrackingItem item) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('删除跟踪'),
        content: Text('确定要删除「${item.title}」的跟踪记录吗？'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('取消')),
          TextButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('删除')),
        ],
      ),
    );
    if (confirmed != true) return;
    setState(() => _updating = true);
    try {
      await _apiClient.deleteTracking(item.jobId);
      await _loadTracking();
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('删除失败: $error')),
        );
      }
    } finally {
      if (mounted) setState(() => _updating = false);
    }
  }

  void _showStatusSheet(JobTrackingItem item) {
    final availableStatuses = _statusGroups.where((s) => s != item.trackingStatus).toList();
    showModalBottomSheet(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Padding(
              padding: const EdgeInsets.all(16),
              child: Text('更新「${item.title}」状态', style: Theme.of(ctx).textTheme.titleMedium),
            ),
            ...availableStatuses.map((status) => ListTile(
              leading: Icon(_statusIcon[status], color: _statusColor[status]),
              title: Text(_statusLabel[status] ?? status),
              onTap: () { Navigator.pop(ctx); _updateStatus(item, status); },
            )),
            ListTile(
              leading: const Icon(Icons.delete_outline, color: Colors.red),
              title: const Text('删除跟踪', style: TextStyle(color: Colors.red)),
              onTap: () { Navigator.pop(ctx); _deleteTracking(item); },
            ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error != null) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(_error!, textAlign: TextAlign.center),
            const SizedBox(height: 12),
            FilledButton(onPressed: _loadTracking, child: const Text('重试')),
          ],
        ),
      );
    }

    final body = _items.isEmpty
        ? _buildEmptyState()
        : RefreshIndicator(
            onRefresh: _loadTracking,
            child: ListView(
              padding: const EdgeInsets.all(16),
              children: [
                _buildSummaryBar(),
                const SizedBox(height: 16),
                ..._buildGroupedList(),
              ],
            ),
          );

    return Scaffold(
      body: Column(
        children: [
          if (_updating) const LinearProgressIndicator(minHeight: 2),
          Expanded(child: body),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () async {
          final result = await Navigator.of(context).push<bool>(
            MaterialPageRoute(builder: (_) => const ImportJobPage()),
          );
          if (result == true) _loadTracking();
        },
        icon: const Icon(Icons.add),
        label: const Text('导入职位'),
      ),
    );
  }

  Widget _buildEmptyState() {
    return ListView(
      children: [
        const SizedBox(height: 80),
        const Icon(Icons.work_history_outlined, size: 72, color: Colors.grey),
        const SizedBox(height: 16),
        const Center(child: Text('暂无跟踪的投递', style: TextStyle(fontSize: 16, color: Colors.grey))),
        const SizedBox(height: 8),
        const Center(child: Text('点击右下角按钮导入感兴趣的外部职位', style: TextStyle(color: Colors.grey))),
        const SizedBox(height: 32),
        Center(
          child: FilledButton.icon(
            onPressed: () async {
              final result = await Navigator.of(context).push<bool>(
                MaterialPageRoute(builder: (_) => const ImportJobPage()),
              );
              if (result == true) _loadTracking();
            },
            icon: const Icon(Icons.add),
            label: const Text('导入第一个职位'),
          ),
        ),
      ],
    );
  }

  Widget _buildSummaryBar() {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Wrap(
          spacing: 8,
          runSpacing: 8,
          children: _statusGroups.map((status) {
            final count = _getCount(status);
            return Chip(
              avatar: Icon(_statusIcon[status], size: 18, color: _statusColor[status]),
              label: Text('${_statusLabel[status]} $count', style: const TextStyle(fontSize: 12)),
              backgroundColor: _statusColor[status]!.withValues(alpha: 0.1),
              side: BorderSide(color: _statusColor[status]!.withValues(alpha: 0.3)),
            );
          }).toList(),
        ),
      ),
    );
  }

  int _getCount(String status) {
    return switch (status) {
      'saved' => _summary.saved,
      'applied' => _summary.applied,
      'interview' => _summary.interview,
      'offer' => _summary.offer,
      'accepted' => _summary.accepted,
      'rejected' => _summary.rejected,
      _ => 0,
    };
  }

  List<Widget> _buildGroupedList() {
    final grouped = <String, List<JobTrackingItem>>{};
    for (final item in _items) {
      grouped.putIfAbsent(item.trackingStatus, () => []).add(item);
    }

    final widgets = <Widget>[];
    for (final status in _statusGroups) {
      final items = grouped[status];
      if (items == null || items.isEmpty) continue;
      widgets.add(
        Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: Row(
            children: [
              Icon(_statusIcon[status], size: 20, color: _statusColor[status]),
              const SizedBox(width: 6),
              Text(
                _statusLabel[status] ?? status,
                style: TextStyle(
                  fontSize: 15, fontWeight: FontWeight.w600,
                  color: _statusColor[status],
                ),
              ),
              const SizedBox(width: 8),
              Text('${items.length}', style: const TextStyle(color: Colors.grey)),
            ],
          ),
        ),
      );
      for (final item in items) {
        widgets.add(_buildItemCard(item));
      }
      widgets.add(const SizedBox(height: 8));
    }
    return widgets;
  }

  Widget _buildItemCard(JobTrackingItem item) {
    final color = _statusColor[item.trackingStatus] ?? Colors.grey;
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () => _showStatusSheet(item),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(item.title, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 15)),
                  ),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                    decoration: BoxDecoration(
                      color: color.withValues(alpha: 0.1),
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: color.withValues(alpha: 0.3)),
                    ),
                    child: Text(_statusLabel[item.trackingStatus] ?? item.trackingStatus,
                      style: TextStyle(fontSize: 11, color: color, fontWeight: FontWeight.w500)),
                  ),
                ],
              ),
              const SizedBox(height: 6),
              Text([item.companyName, item.cityName, item.salaryText].where((s) => s.isNotEmpty).join(' · '),
                style: const TextStyle(color: Colors.grey, fontSize: 13)),
              if (item.sourceName.isNotEmpty) ...[
                const SizedBox(height: 4),
                Row(
                  children: [
                    Icon(Icons.link, size: 14, color: Colors.grey.shade400),
                    const SizedBox(width: 4),
                    Text(item.sourceName, style: TextStyle(fontSize: 12, color: Colors.grey.shade500)),
                    if (item.notes.isNotEmpty) ...[
                      const SizedBox(width: 12),
                      Icon(Icons.notes, size: 14, color: Colors.grey.shade400),
                      const SizedBox(width: 4),
                      Expanded(child: Text(item.notes, maxLines: 1, overflow: TextOverflow.ellipsis,
                        style: TextStyle(fontSize: 12, color: Colors.grey.shade500))),
                    ],
                  ],
                ),
              ],
              if (item.appliedAt.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text('投递时间: ${item.appliedAt}', style: TextStyle(fontSize: 11, color: Colors.grey.shade400)),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
