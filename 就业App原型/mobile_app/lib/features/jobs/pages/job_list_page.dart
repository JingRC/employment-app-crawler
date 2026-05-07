import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../../core/network/api_client.dart';
import '../../../shared/models/job_item.dart';
import 'job_detail_page.dart';

class JobListPage extends StatefulWidget {
  const JobListPage({
    this.embedded = false,
    this.initialKeyword = '',
    this.initialCityName = '青岛',
    this.pageTitle = '职位列表',
    super.key,
  });

  final bool embedded;
  final String initialKeyword;
  final String initialCityName;
  final String pageTitle;

  @override
  State<JobListPage> createState() => _JobListPageState();
}

class _JobListPageState extends State<JobListPage> {
  static const int _pageSize = 6;
  static const String _historyKey = 'job_search_history';

  final ApiClient _apiClient = ApiClient();
  final TextEditingController _keywordController = TextEditingController();
  final TextEditingController _cityController = TextEditingController(text: '青岛');
  final ScrollController _scrollController = ScrollController();

  bool _loading = true;
  bool _loadingMore = false;
  bool _savingSearch = false;
  String? _error;
  List<JobItem> _jobs = const [];
  List<String> _searchHistory = const [];
  int _currentPage = 1;
  int _total = 0;

  bool get _hasMore => _jobs.length < _total;

  @override
  void initState() {
    super.initState();
    _keywordController.text = widget.initialKeyword;
    _cityController.text = widget.initialCityName;
    _scrollController.addListener(_onScroll);
    _initializePage();
  }

  @override
  void dispose() {
    _keywordController.dispose();
    _cityController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  Future<void> _initializePage() async {
    await _loadSearchHistory();
    await _loadJobs(reset: true);
  }

  Future<void> _loadSearchHistory() async {
    final preferences = await SharedPreferences.getInstance();
    final history = preferences.getStringList(_historyKey) ?? <String>[];
    if (!mounted) {
      return;
    }
    setState(() {
      _searchHistory = history;
    });
  }

  Future<void> _saveSearchHistory() async {
    final keyword = _keywordController.text.trim();
    final city = _cityController.text.trim();
    final queryLabel = [keyword, city].where((item) => item.isNotEmpty).join(' · ');
    if (queryLabel.isEmpty) {
      return;
    }

    final updated = <String>[queryLabel, ..._searchHistory.where((item) => item != queryLabel)]
        .take(8)
        .toList();
    final preferences = await SharedPreferences.getInstance();
    await preferences.setStringList(_historyKey, updated);
    if (!mounted) {
      return;
    }
    setState(() {
      _searchHistory = updated;
    });
  }

  Future<void> _loadJobs({required bool reset}) async {
    final nextPage = reset ? 1 : _currentPage + 1;

    setState(() {
      if (reset) {
        _loading = true;
        _error = null;
      } else {
        _loadingMore = true;
      }
    });

    try {
      final result = await _apiClient.fetchJobs(
        keyword: _keywordController.text,
        cityName: _cityController.text,
        page: nextPage,
        pageSize: _pageSize,
      );
      if (!mounted) {
        return;
      }
      setState(() {
        _currentPage = result.page;
        _total = result.total;
        _jobs = reset ? result.items : [..._jobs, ...result.items];
      });
      if (reset) {
        await _saveSearchHistory();
      }
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
          if (reset) {
            _loading = false;
          }
          _loadingMore = false;
        });
      }
    }
  }

  void _onScroll() {
    if (!_scrollController.hasClients || _loading || _loadingMore || !_hasMore) {
      return;
    }

    final position = _scrollController.position;
    if (position.pixels >= position.maxScrollExtent - 160) {
      _loadJobs(reset: false);
    }
  }

  void _applyHistoryItem(String item) {
    final parts = item.split(' · ');
    setState(() {
      _keywordController.text = parts.isNotEmpty ? parts.first : '';
      _cityController.text = parts.length > 1 ? parts.sublist(1).join(' · ') : '';
    });
    _loadJobs(reset: true);
  }

  Future<void> _clearSearchHistory() async {
    final preferences = await SharedPreferences.getInstance();
    await preferences.remove(_historyKey);
    if (!mounted) {
      return;
    }
    setState(() {
      _searchHistory = const [];
    });
  }

  Future<void> _saveCurrentSearch() async {
    final keyword = _keywordController.text.trim();
    final city = _cityController.text.trim();
    if (keyword.isEmpty && city.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('请先输入关键词或城市后再保存订阅')),
      );
      return;
    }

    setState(() {
      _savingSearch = true;
    });
    try {
      final result = await _apiClient.createSavedSearch(
        keyword: keyword,
        cityName: city,
      );
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('已保存订阅：${[result.keyword, result.cityName].where((item) => item.isNotEmpty).join(' · ')}'),
        ),
      );
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('保存订阅失败: $error')),
        );
      }
    } finally {
      if (mounted) {
        setState(() {
          _savingSearch = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final content = Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              children: [
                TextField(
                  controller: _keywordController,
                  decoration: const InputDecoration(
                    labelText: '关键词',
                    hintText: '输入职位关键词，例如 Java',
                    border: OutlineInputBorder(),
                  ),
                  onSubmitted: (_) => _loadJobs(reset: true),
                ),
                const SizedBox(height: 12),
                Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: _cityController,
                        decoration: const InputDecoration(
                          labelText: '城市',
                          border: OutlineInputBorder(),
                        ),
                        onSubmitted: (_) => _loadJobs(reset: true),
                      ),
                    ),
                    const SizedBox(width: 12),
                    FilledButton(
                      onPressed: () => _loadJobs(reset: true),
                      child: const Text('搜索'),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                Align(
                  alignment: Alignment.centerRight,
                  child: FilledButton.tonalIcon(
                    onPressed: _savingSearch ? null : _saveCurrentSearch,
                    icon: _savingSearch
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.notifications_active_outlined),
                    label: const Text('保存当前搜索'),
                  ),
                ),
                if (_searchHistory.isNotEmpty) ...[
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      const Text('搜索历史'),
                      const Spacer(),
                      TextButton(
                        onPressed: _clearSearchHistory,
                        child: const Text('清空'),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Align(
                    alignment: Alignment.centerLeft,
                    child: Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: _searchHistory
                          .map(
                            (item) => ActionChip(
                              label: Text(item),
                              onPressed: () => _applyHistoryItem(item),
                            ),
                          )
                          .toList(),
                    ),
                  ),
                ],
              ],
            ),
          ),
          Expanded(
            child: _buildBody(context),
          ),
        ],
    );

    if (widget.embedded) {
      return content;
    }

    return Scaffold(
      appBar: AppBar(title: Text(widget.pageTitle)),
      body: content,
    );
  }

  Widget _buildBody(BuildContext context) {
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
              FilledButton(
                onPressed: () => _loadJobs(reset: true),
                child: const Text('重试'),
              ),
            ],
          ),
        ),
      );
    }

    if (_jobs.isEmpty) {
      return RefreshIndicator(
        onRefresh: () => _loadJobs(reset: true),
        child: ListView(
          children: const [
            SizedBox(height: 120),
            Icon(Icons.search_off, size: 56, color: Colors.grey),
            SizedBox(height: 16),
            Center(child: Text('没有查到职位数据')),
            SizedBox(height: 8),
            Center(child: Text('试试调整关键词或城市条件')),
          ],
        ),
      );
    }

    return RefreshIndicator(
      onRefresh: () => _loadJobs(reset: true),
      child: ListView.separated(
        controller: _scrollController,
        itemCount: _jobs.length + 1,
        separatorBuilder: (_, __) => const Divider(height: 1),
        itemBuilder: (context, index) {
          if (index == _jobs.length) {
            return _buildFooter();
          }

          final item = _jobs[index];
          final subtitleParts = <String>[item.companyName, item.cityName];
          if (item.salaryText.isNotEmpty) {
            subtitleParts.add(item.salaryText);
          }
          return ListTile(
            title: Text(item.title),
            subtitle: Text(subtitleParts.join(' · ')),
            trailing: const Icon(Icons.chevron_right),
            onTap: () {
              Navigator.of(context).push(
                MaterialPageRoute<void>(
                  builder: (_) => JobDetailPage(jobId: item.jobId),
                ),
              );
            },
          );
        },
      ),
    );
  }

  Widget _buildFooter() {
    if (_loadingMore) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 16),
        child: Center(child: CircularProgressIndicator()),
      );
    }

    if (_hasMore) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 16),
        child: Center(child: Text('继续下滑加载更多职位')),
      );
    }

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 16),
      child: Center(child: Text('已加载全部 $_total 条职位')),
    );
  }
}
