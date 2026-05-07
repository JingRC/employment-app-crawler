import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../core/network/api_client.dart';
import '../../notifications/pages/notifications_page.dart';
import '../../../shared/models/job_detail.dart';
import '../../../shared/models/job_timeline_entry.dart';
import '../../../shared/models/job_timeline_event.dart';
import '../../../shared/models/job_timeline_result.dart';
import '../../../shared/models/notification_item.dart';

class JobDetailPage extends StatefulWidget {
  const JobDetailPage({required this.jobId, super.key});

  final int jobId;

  @override
  State<JobDetailPage> createState() => _JobDetailPageState();
}

class _JobDetailPageState extends State<JobDetailPage> {
  final ApiClient _apiClient = ApiClient();

  bool _loading = true;
  bool _submittingJobFavorite = false;
  bool _submittingFavorite = false;
  String? _error;
  final Set<String> _expandedTimelineEntries = <String>{};
  JobDetail? _jobDetail;
  JobTimelineResult _timeline = const JobTimelineResult(
    notifications: <NotificationItem>[],
    events: <JobTimelineEvent>[],
    timeline: <JobTimelineEntry>[],
  );

  @override
  void initState() {
    super.initState();
    _loadDetail();
  }

  Future<void> _loadDetail() async {
    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final results = await Future.wait<dynamic>([
        _apiClient.fetchJobDetail(widget.jobId),
        _apiClient.fetchJobTimeline(widget.jobId),
      ]);
      if (!mounted) {
        return;
      }
      setState(() {
        _jobDetail = results[0] as JobDetail;
        _timeline = results[1] as JobTimelineResult;
      });
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

  Uri? _normalizeUrl(String value) {
    final trimmed = value.trim();
    if (trimmed.isEmpty) {
      return null;
    }

    final parsed = Uri.tryParse(trimmed);
    if (parsed != null && parsed.hasScheme) {
      return parsed;
    }

    return Uri.tryParse('https://$trimmed');
  }

  void _showMessage(String message) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _openOfficialApplyUrl(String urlText) async {
    final uri = _normalizeUrl(urlText);
    if (uri == null) {
      _showMessage('投递链接格式无效');
      return;
    }

    final launched = await launchUrl(uri, mode: LaunchMode.externalApplication);
    if (!launched && mounted) {
      _showMessage('无法打开官网链接');
    }
  }

  Future<void> _favoriteCompany(JobDetail job) async {
    if (_submittingFavorite || job.companyId == 0) {
      return;
    }

    setState(() {
      _submittingFavorite = true;
    });

    try {
      await _apiClient.favoriteCompany(
        companyId: job.companyId,
        companyName: job.companyName,
      );
      if (mounted) {
        _showMessage('已收藏 ${job.companyName}');
      }
    } catch (error) {
      if (mounted) {
        _showMessage('收藏失败: $error');
      }
    } finally {
      if (mounted) {
        setState(() {
          _submittingFavorite = false;
        });
      }
    }
  }

  Future<void> _favoriteJob(JobDetail job) async {
    if (_submittingJobFavorite || job.jobId <= 0) {
      return;
    }

    setState(() {
      _submittingJobFavorite = true;
    });

    try {
      await _apiClient.favoriteJob(jobId: job.jobId);
      if (mounted) {
        _showMessage('已收藏 ${job.title}');
      }
    } catch (error) {
      if (mounted) {
        _showMessage('收藏职位失败: $error');
      }
    } finally {
      if (mounted) {
        setState(() {
          _submittingJobFavorite = false;
        });
      }
    }
  }

  Future<void> _copyLink(String urlText) async {
    if (urlText.trim().isEmpty) {
      _showMessage('暂无可复制的链接');
      return;
    }
    await Clipboard.setData(ClipboardData(text: urlText.trim()));
    if (mounted) {
      _showMessage('链接已复制');
    }
  }

  String _formatTimelineLabel(JobTimelineEntry entry) {
    if (entry.entryKind == 'notification') {
      switch (entry.notificationType) {
        case 'new_job':
          return '订阅命中';
        case 'job_updated':
          return '通知';
        case 'job_closed':
          return '下线提醒';
        case 'company_new_job':
          return '企业提醒';
        default:
          return entry.notificationType.isEmpty ? '通知' : entry.notificationType;
      }
    }

    switch (entry.eventType) {
      case 'new_job':
        return '新增职位';
      case 'job_updated':
        return '职位更新';
      case 'salary_changed':
        return '薪资变化';
      case 'status_changed':
        return '状态变化';
      case 'job_closed':
        return '职位下线';
      default:
        return entry.eventType.isEmpty ? '事件' : entry.eventType;
    }
  }

  String _formatTimelineMeta(JobTimelineEntry entry) {
    if (entry.entryKind == 'notification') {
      return [entry.actionSourceName, entry.createdAt].where((value) => value.isNotEmpty).join(' · ');
    }
    return [entry.sourceName.isNotEmpty ? entry.sourceName : entry.sourceCode, entry.createdAt]
        .where((value) => value.isNotEmpty)
        .join(' · ');
  }

  String _formatTimelineGroupTitle(String createdAt) {
    final text = createdAt.trim();
    if (text.isEmpty) {
      return '更早';
    }
    try {
      final dt = DateTime.parse(text.replaceFirst(' ', 'T'));
      return '${dt.year}年${dt.month}月${dt.day}日';
    } catch (_) {
      return text.length >= 10 ? text.substring(0, 10) : text;
    }
  }

  String _timelineEntryKey(JobTimelineEntry entry) {
    return [
      entry.entryKind,
      entry.createdAt,
      entry.title,
      entry.content,
      entry.notificationType,
      entry.eventType,
    ].join('|');
  }

  Future<void> _handleTimelineTap(JobTimelineEntry entry) async {
    if (entry.entryKind == 'notification') {
      await Navigator.of(context).push(
        MaterialPageRoute<void>(
          builder: (_) => NotificationsPage(focusRelatedJobId: widget.jobId),
        ),
      );
      return;
    }

    final key = _timelineEntryKey(entry);
    setState(() {
      if (_expandedTimelineEntries.contains(key)) {
        _expandedTimelineEntries.remove(key);
      } else {
        _expandedTimelineEntries.add(key);
      }
    });
  }

  List<Widget> _buildTimelineSections(ThemeData theme) {
    if (_timeline.timeline.isEmpty) {
      return const <Widget>[];
    }

    final grouped = <String, List<JobTimelineEntry>>{};
    for (final entry in _timeline.timeline) {
      final key = _formatTimelineGroupTitle(entry.createdAt);
      grouped.putIfAbsent(key, () => <JobTimelineEntry>[]).add(entry);
    }

    final widgets = <Widget>[];
    grouped.forEach((groupTitle, entries) {
      widgets.add(
        Padding(
          padding: const EdgeInsets.only(top: 4, bottom: 8),
          child: Text(
            groupTitle,
            style: theme.textTheme.labelLarge?.copyWith(fontWeight: FontWeight.w700),
          ),
        ),
      );
      widgets.addAll(entries.map((entry) {
        final isNotification = entry.entryKind == 'notification';
        final key = _timelineEntryKey(entry);
        final isExpanded = _expandedTimelineEntries.contains(key);
        final tint = isNotification ? const Color(0xFFEFF6FF) : const Color(0xFFFFF7ED);
        final borderColor = isNotification ? const Color(0xFF60A5FA) : const Color(0xFFF59E0B);
        return Container(
          margin: const EdgeInsets.only(bottom: 10),
          decoration: BoxDecoration(
            color: tint,
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: borderColor.withValues(alpha: 0.35)),
          ),
          child: ListTile(
            onTap: () => _handleTimelineTap(entry),
            leading: CircleAvatar(
              backgroundColor: Colors.white,
              child: Icon(
                isNotification
                    ? (entry.isRead ? Icons.mark_email_read_outlined : Icons.notifications_active)
                    : Icons.timeline,
                color: borderColor,
              ),
            ),
            title: Text(entry.title.isEmpty ? _formatTimelineLabel(entry) : entry.title),
            subtitle: Text(
              [
                isNotification ? '通知记录' : '职位事件',
                _formatTimelineLabel(entry),
                entry.content,
                _formatTimelineMeta(entry),
                if (!isNotification && isExpanded) '详情说明：${entry.content.isEmpty ? _formatTimelineLabel(entry) : entry.content}',
                if (isNotification) '点击打开通知页查看原始通知记录',
                if (!isNotification && !isExpanded) '点击展开变更详情',
                if (!isNotification && isExpanded) '再次点击可收起',
              ].where((value) => value.isNotEmpty).join('\n'),
            ),
            trailing: Icon(
              isNotification
                  ? Icons.open_in_new
                  : (isExpanded ? Icons.expand_less : Icons.expand_more),
              color: borderColor,
            ),
            isThreeLine: isNotification || isExpanded,
          ),
        );
      }));
    });

    return widgets;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('职位详情')),
      body: _buildBody(),
    );
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
              FilledButton(onPressed: _loadDetail, child: const Text('重试')),
            ],
          ),
        ),
      );
    }

    final job = _jobDetail;
    if (job == null) {
      return const Center(child: Text('没有找到职位详情'));
    }

    final titleStyle = Theme.of(context).textTheme.headlineSmall?.copyWith(
          fontWeight: FontWeight.bold,
        );

    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(job.title, style: titleStyle),
          const SizedBox(height: 8),
          Text('${job.companyName} · ${job.cityName} ${job.districtName}'.trim()),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              if (job.salaryText.isNotEmpty) Chip(label: Text(job.salaryText)),
              if (job.degreeText.isNotEmpty) Chip(label: Text(job.degreeText)),
              if (job.experienceText.isNotEmpty) Chip(label: Text(job.experienceText)),
            ],
          ),
          const SizedBox(height: 16),
          const Text(
            '职位描述',
            style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 8),
          Expanded(
            child: SingleChildScrollView(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(job.descriptionText.isEmpty ? '暂无职位描述' : job.descriptionText),
                  if (_timeline.timeline.isNotEmpty) ...[
                    const SizedBox(height: 20),
                    const Text(
                      '动态时间轴',
                      style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
                    ),
                    const SizedBox(height: 8),
                    ..._buildTimelineSections(Theme.of(context)),
                  ],
                ],
              ),
            ),
          ),
          const SizedBox(height: 16),
          if (job.officialApplyUrl.isNotEmpty) ...[
            SelectableText(
              job.officialApplyUrl,
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 8),
          ],
          Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: _submittingJobFavorite ? null : () => _favoriteJob(job),
                  icon: _submittingJobFavorite
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.bookmark_add_outlined),
                  label: const Text('收藏职位'),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: _submittingFavorite ? null : () => _favoriteCompany(job),
                  icon: _submittingFavorite
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.favorite_border),
                  label: const Text('收藏公司'),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: job.officialApplyUrl.isEmpty ? null : () => _copyLink(job.officialApplyUrl),
                  icon: const Icon(Icons.link),
                  label: const Text('复制链接'),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              onPressed: job.officialApplyUrl.isEmpty ? null : () => _openOfficialApplyUrl(job.officialApplyUrl),
              child: Text(job.officialApplyUrl.isEmpty ? '暂无投递链接' : '打开官网投递'),
            ),
          ),
        ],
      ),
    );
  }
}
