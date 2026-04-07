import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../core/network/api_client.dart';
import '../../../shared/models/job_detail.dart';

class JobDetailPage extends StatefulWidget {
  const JobDetailPage({required this.jobId, super.key});

  final int jobId;

  @override
  State<JobDetailPage> createState() => _JobDetailPageState();
}

class _JobDetailPageState extends State<JobDetailPage> {
  final ApiClient _apiClient = ApiClient();

  bool _loading = true;
  bool _submittingFavorite = false;
  String? _error;
  JobDetail? _jobDetail;

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
      final detail = await _apiClient.fetchJobDetail(widget.jobId);
      if (!mounted) {
        return;
      }
      setState(() {
        _jobDetail = detail;
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
              child: Text(
                job.descriptionText.isEmpty ? '暂无职位描述' : job.descriptionText,
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
              const SizedBox(width: 12),
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: job.officialApplyUrl.isEmpty
                      ? null
                      : () => _copyLink(job.officialApplyUrl),
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
              onPressed: job.officialApplyUrl.isEmpty
                  ? null
                  : () => _openOfficialApplyUrl(job.officialApplyUrl),
              child: Text(job.officialApplyUrl.isEmpty ? '暂无投递链接' : '打开官网投递'),
            ),
          ),
        ],
      ),
    );
  }
}
