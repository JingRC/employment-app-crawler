import 'package:flutter/material.dart';

import '../../../core/network/api_client.dart';
import '../../jobs/pages/job_detail_page.dart';
import '../../../shared/models/notification_item.dart';
import '../../../shared/models/notification_stats.dart';

class NotificationsPage extends StatefulWidget {
  const NotificationsPage({
    this.embedded = false,
    this.refreshToken = 0,
    this.focusRelatedJobId,
    this.onUnreadChanged,
    super.key,
  });

  final bool embedded;
  final int refreshToken;
  final int? focusRelatedJobId;
  final ValueChanged<int>? onUnreadChanged;

  @override
  State<NotificationsPage> createState() => _NotificationsPageState();
}

class _NotificationsPageState extends State<NotificationsPage> {
  final ApiClient _apiClient = ApiClient();
  final ScrollController _scrollController = ScrollController();
  final Map<int, GlobalKey> _notificationKeys = <int, GlobalKey>{};

  bool _loading = true;
  bool _markingAllRead = false;
  String? _error;
  int? _highlightedNotificationId;
  List<NotificationItem> _notifications = const [];
  NotificationStats _stats = const NotificationStats(total: 0, unread: 0);

  @override
  void initState() {
    super.initState();
    _loadNotifications();
  }

  @override
  void didUpdateWidget(covariant NotificationsPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.refreshToken != oldWidget.refreshToken) {
      _loadNotifications();
    }
    if (widget.focusRelatedJobId != oldWidget.focusRelatedJobId) {
      _highlightedNotificationId = null;
      _maybeFocusTargetNotification();
    }
  }

  @override
  void dispose() {
    _scrollController.dispose();
    super.dispose();
  }

  Future<void> _loadNotifications() async {
    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final futures = await Future.wait<dynamic>([
        _apiClient.fetchNotifications(),
        _apiClient.fetchNotificationStats(),
      ]);
      if (!mounted) {
        return;
      }
      setState(() {
        _notifications = futures[0] as List<NotificationItem>;
        _stats = futures[1] as NotificationStats;
      });
      widget.onUnreadChanged?.call(_stats.unread);
      _maybeFocusTargetNotification();
    } catch (error) {
      if (!mounted) {
        return;
      }
      setState(() {
        _error = error.toString();
      });
    } finally {
      if (mounted) {
        setState(() {
          _loading = false;
        });
      }
    }
  }

  void _maybeFocusTargetNotification() {
    final focusJobId = widget.focusRelatedJobId;
    if (!mounted || focusJobId == null || _notifications.isEmpty) {
      return;
    }

    final target = _notifications.cast<NotificationItem?>().firstWhere(
          (item) => item != null && item.relatedJobId == focusJobId,
          orElse: () => null,
        );
    if (target == null) {
      return;
    }

    setState(() {
      _highlightedNotificationId = target.notificationId;
    });

    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) {
        return;
      }
      final targetKey = _notificationKeys[target.notificationId];
      final targetContext = targetKey?.currentContext;
      if (targetContext != null) {
        Scrollable.ensureVisible(
          targetContext,
          duration: const Duration(milliseconds: 350),
          curve: Curves.easeOutCubic,
          alignment: 0.2,
        );
      }
    });
  }

  Future<void> _markAllRead() async {
    if (_markingAllRead) {
      return;
    }
    setState(() {
      _markingAllRead = true;
    });
    try {
      final affected = await _apiClient.markAllNotificationsRead();
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(affected > 0 ? '已标记 $affected 条通知为已读' : '当前没有未读通知')),
      );
      await _loadNotifications();
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('全部已读失败: $error')),
        );
      }
    } finally {
      if (mounted) {
        setState(() {
          _markingAllRead = false;
        });
      }
    }
  }

  Future<void> _openNotification(NotificationItem item) async {
    setState(() {
      _highlightedNotificationId = item.notificationId;
    });
    if (!item.isRead) {
      await _apiClient.markNotificationRead(item.notificationId);
      await _loadNotifications();
    }
    if (!mounted || item.relatedJobId == null || item.relatedJobId! <= 0) {
      return;
    }
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => JobDetailPage(jobId: item.relatedJobId!),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final body = _buildBody();
    if (widget.embedded) {
      return body;
    }
    return Scaffold(appBar: AppBar(title: const Text('通知')), body: body);
  }

  Widget _buildBody() {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }

    if (_error != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(_error!, textAlign: TextAlign.center),
              const SizedBox(height: 12),
              FilledButton(onPressed: _loadNotifications, child: const Text('重试')),
            ],
          ),
        ),
      );
    }

    return Column(
      children: [
        if (widget.focusRelatedJobId != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 0),
            child: Align(
              alignment: Alignment.centerLeft,
              child: Chip(
                avatar: const Icon(Icons.my_location, size: 18),
                label: Text('已定位到职位 ${widget.focusRelatedJobId} 的相关通知'),
              ),
            ),
          ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
          child: Row(
            children: [
              Expanded(
                child: Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    Chip(label: Text('累计 ${_stats.total}')),
                    Chip(label: Text('未读 ${_stats.unread}')),
                  ],
                ),
              ),
              FilledButton.tonal(
                onPressed: (_stats.unread <= 0 || _markingAllRead) ? null : _markAllRead,
                child: Text(_markingAllRead ? '处理中...' : '全部已读'),
              ),
            ],
          ),
        ),
        Expanded(
          child: _notifications.isEmpty
              ? const Center(child: Text('暂无通知'))
              : RefreshIndicator(
                  onRefresh: _loadNotifications,
                  child: ListView.separated(
                  controller: _scrollController,
                  itemCount: _notifications.length,
                  separatorBuilder: (_, __) => const Divider(height: 1),
                  itemBuilder: (context, index) {
                    final item = _notifications[index];
                    final isHighlighted = item.notificationId == _highlightedNotificationId;
                    final itemKey = _notificationKeys.putIfAbsent(
                      item.notificationId,
                      () => GlobalKey(),
                    );
                    return AnimatedContainer(
                      key: itemKey,
                      duration: const Duration(milliseconds: 220),
                      curve: Curves.easeOut,
                      color: isHighlighted
                          ? Theme.of(context).colorScheme.primaryContainer.withValues(alpha: 0.55)
                          : Colors.transparent,
                      child: ListTile(
                        onTap: () => _openNotification(item),
                        leading: Icon(
                          item.isRead ? Icons.mark_email_read_outlined : Icons.notifications_active,
                        ),
                        title: Text(item.title),
                        subtitle: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Text(item.content),
                            const SizedBox(height: 4),
                            Text(
                              [item.actionSourceName, item.createdAt]
                                  .where((value) => value.isNotEmpty)
                                  .join(' · '),
                              style: Theme.of(context).textTheme.bodySmall,
                            ),
                          ],
                        ),
                        trailing: item.isRead
                            ? (isHighlighted ? const Icon(Icons.my_location) : null)
                            : Column(
                                mainAxisAlignment: MainAxisAlignment.center,
                                children: [
                                  const Chip(label: Text('未读')),
                                  if (isHighlighted) const Icon(Icons.my_location, size: 18),
                                ],
                              ),
                      ),
                    );
                  },
                ),
                ),
        ),
      ],
    );
  }
}
