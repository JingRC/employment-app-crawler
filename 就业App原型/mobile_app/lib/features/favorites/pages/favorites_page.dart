import 'package:flutter/material.dart';

import '../../../core/network/api_client.dart';
import '../../../shared/models/favorite_company.dart';
import '../../../shared/models/favorite_job.dart';
import '../../../shared/models/saved_search_item.dart';
import '../../jobs/pages/job_detail_page.dart';
import '../../jobs/pages/job_list_page.dart';

enum FavoriteTab { jobs, companies, searches }

class FavoritesPage extends StatefulWidget {
  const FavoritesPage({this.embedded = false, this.refreshToken = 0, super.key});

  final bool embedded;
  final int refreshToken;

  @override
  State<FavoritesPage> createState() => _FavoritesPageState();
}

class _FavoritesPageState extends State<FavoritesPage> {
  final ApiClient _apiClient = ApiClient();

  bool _loading = true;
  bool _updating = false;
  String? _error;
  FavoriteTab _tab = FavoriteTab.jobs;
  List<FavoriteJob> _jobs = const [];
  List<FavoriteCompany> _companies = const [];
  List<SavedSearchItem> _searches = const [];

  @override
  void initState() {
    super.initState();
    _loadFavorites();
  }

  @override
  void didUpdateWidget(covariant FavoritesPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.refreshToken != oldWidget.refreshToken) {
      _loadFavorites();
    }
  }

  Future<void> _loadFavorites() async {
    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final futures = await Future.wait<dynamic>([
        _apiClient.fetchFavoriteJobs(),
        _apiClient.fetchFavoriteCompanies(),
        _apiClient.fetchSavedSearches(),
      ]);
      if (!mounted) {
        return;
      }
      setState(() {
        _jobs = futures[0] as List<FavoriteJob>;
        _companies = futures[1] as List<FavoriteCompany>;
        _searches = futures[2] as List<SavedSearchItem>;
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

  Future<void> _removeFavoriteJob(int jobId) async {
    setState(() {
      _updating = true;
    });
    try {
      await _apiClient.unfavoriteJob(jobId);
      await _loadFavorites();
    } finally {
      if (mounted) {
        setState(() {
          _updating = false;
        });
      }
    }
  }

  Future<void> _toggleSavedSearch(SavedSearchItem item, bool enabled) async {
    setState(() {
      _updating = true;
    });
    try {
      await _apiClient.updateSavedSearch(searchId: item.searchId, enabled: enabled);
      await _loadFavorites();
    } finally {
      if (mounted) {
        setState(() {
          _updating = false;
        });
      }
    }
  }

  Future<void> _deleteSavedSearch(int searchId) async {
    setState(() {
      _updating = true;
    });
    try {
      await _apiClient.deleteSavedSearch(searchId);
      await _loadFavorites();
    } finally {
      if (mounted) {
        setState(() {
          _updating = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final body = _buildBody();
    if (widget.embedded) {
      return body;
    }
    return Scaffold(appBar: AppBar(title: const Text('收藏')), body: body);
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
              FilledButton(onPressed: _loadFavorites, child: const Text('重试')),
            ],
          ),
        ),
      );
    }

    final body = switch (_tab) {
      FavoriteTab.jobs => _buildJobsTab(),
      FavoriteTab.companies => _buildCompaniesTab(),
      FavoriteTab.searches => _buildSearchesTab(),
    };

    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
          child: SegmentedButton<FavoriteTab>(
            segments: const [
              ButtonSegment<FavoriteTab>(value: FavoriteTab.jobs, label: Text('职位')),
              ButtonSegment<FavoriteTab>(value: FavoriteTab.companies, label: Text('企业')),
              ButtonSegment<FavoriteTab>(value: FavoriteTab.searches, label: Text('订阅')),
            ],
            selected: <FavoriteTab>{_tab},
            onSelectionChanged: (selection) {
              setState(() {
                _tab = selection.first;
              });
            },
          ),
        ),
        if (_updating) const LinearProgressIndicator(minHeight: 2),
        Expanded(child: body),
      ],
    );
  }

  Widget _buildJobsTab() {
    if (_jobs.isEmpty) {
      return const Center(child: Text('暂无收藏职位'));
    }
    return RefreshIndicator(
      onRefresh: _loadFavorites,
      child: ListView.separated(
        itemCount: _jobs.length,
        separatorBuilder: (_, __) => const Divider(height: 1),
        itemBuilder: (context, index) {
          final item = _jobs[index];
          return ListTile(
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute<void>(builder: (_) => JobDetailPage(jobId: item.jobId)),
            ),
            leading: const CircleAvatar(child: Icon(Icons.work_outline)),
            title: Text(item.title),
            subtitle: Text([
              item.companyName,
              item.cityName,
              item.salaryText,
              item.sourceName,
            ].where((value) => value.isNotEmpty).join(' · ')),
            trailing: IconButton(
              onPressed: _updating ? null : () => _removeFavoriteJob(item.jobId),
              icon: const Icon(Icons.delete_outline),
            ),
          );
        },
      ),
    );
  }

  Widget _buildCompaniesTab() {
    if (_companies.isEmpty) {
      return const Center(child: Text('暂无收藏企业'));
    }
    return RefreshIndicator(
      onRefresh: _loadFavorites,
      child: ListView.separated(
        itemCount: _companies.length,
        separatorBuilder: (_, __) => const Divider(height: 1),
        itemBuilder: (context, index) {
          final company = _companies[index];
          return ListTile(
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute<void>(
                builder: (_) => JobListPage(
                  initialKeyword: company.companyName,
                  pageTitle: '${company.companyName} 相关职位',
                ),
              ),
            ),
            leading: const CircleAvatar(child: Icon(Icons.business)),
            title: Text(company.companyName),
            subtitle: Text('企业ID: ${company.companyId} · 点击查看相关职位'),
            trailing: const Icon(Icons.chevron_right),
          );
        },
      ),
    );
  }

  Widget _buildSearchesTab() {
    if (_searches.isEmpty) {
      return const Center(child: Text('暂无搜索订阅'));
    }
    return RefreshIndicator(
      onRefresh: _loadFavorites,
      child: ListView.separated(
        itemCount: _searches.length,
        separatorBuilder: (_, __) => const Divider(height: 1),
        itemBuilder: (context, index) {
          final item = _searches[index];
          final chips = <String>[
            if (item.keyword.isNotEmpty) item.keyword,
            if (item.cityName.isNotEmpty) item.cityName,
            item.notifyFrequency,
          ];
          chips.addAll(item.filters.entries.map((entry) => '${entry.key}:${entry.value}'));
          return ListTile(
            leading: const CircleAvatar(child: Icon(Icons.notifications_active_outlined)),
            title: Text(chips.take(2).join(' · ').isEmpty ? '未命名订阅' : chips.take(2).join(' · ')),
            subtitle: Text([
              if (chips.length > 2) chips.skip(2).join(' · '),
              if (item.lastTriggeredAt.isNotEmpty) '最近触发 ${item.lastTriggeredAt}',
            ].where((value) => value.isNotEmpty).join('\n')),
            isThreeLine: item.lastTriggeredAt.isNotEmpty || chips.length > 2,
            trailing: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Switch(
                  value: item.enabled,
                  onChanged: _updating ? null : (value) => _toggleSavedSearch(item, value),
                ),
                IconButton(
                  onPressed: _updating ? null : () => _deleteSavedSearch(item.searchId),
                  icon: const Icon(Icons.delete_outline),
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}
