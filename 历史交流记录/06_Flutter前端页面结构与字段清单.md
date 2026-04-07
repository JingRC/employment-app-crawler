# Flutter 前端页面结构与页面字段清单

## 一、前端目标

Flutter 前端主要承担以下职责：

1. 提供职位搜索与筛选界面
2. 展示职位列表与职位详情
3. 支持收藏企业、收藏搜索条件
4. 展示职位更新与提醒消息
5. 跳转到官网投递链接或来源链接

推荐前端项目结构：

```text
lib/
  app/
    router/
    theme/
  core/
    constants/
    network/
    storage/
    utils/
  features/
    home/
    jobs/
    company/
    favorites/
    notifications/
    profile/
  shared/
    widgets/
    models/
```

## 二、页面结构设计

## 1. 首页 / 搜索页

### 页面目标

1. 输入关键词
2. 选择城市
3. 快速进入职位列表
4. 展示最近搜索和热门搜索

### 页面字段

1. 搜索关键词 `keyword`
2. 城市 `city_name`
3. 热门关键词列表
4. 最近搜索列表

### 组件建议

1. 搜索框
2. 城市选择器
3. 热门关键词标签
4. 最近搜索列表
5. 搜索按钮

### 接口依赖

1. `GET /api/jobs`

---

## 2. 职位列表页

### 页面目标

1. 展示职位搜索结果
2. 支持筛选和排序
3. 支持收藏企业或进入详情

### 页面字段

每个职位卡片建议展示：

1. `title` 职位名称
2. `company_name` 公司名称
3. `city_name` 城市
4. `district_name` 区县
5. `salary_text` 薪资
6. `degree_text` 学历要求
7. `experience_text` 经验要求
8. `source_name` 来源
9. `published_at` 发布时间
10. `official_apply_url` 官网投递链接

### 筛选条件

1. 城市
2. 学历
3. 经验
4. 公司名
5. 排序方式

### 接口依赖

1. `GET /api/jobs`
2. `POST /api/favorites/companies`

---

## 3. 职位详情页

### 页面目标

1. 展示职位完整信息
2. 跳转官网投递
3. 收藏企业
4. 查看来源链接

### 页面字段

1. `title`
2. `company.company_name`
3. `city_name`
4. `district_name`
5. `salary_text`
6. `degree_text`
7. `experience_text`
8. `job_type`
9. `description_text`
10. `source_name`
11. `source_url`
12. `official_apply_url`
13. `published_at`
14. `status`

### 页面按钮

1. 官网投递
2. 查看来源
3. 收藏企业
4. 分享职位

### 接口依赖

1. `GET /api/jobs/{job_id}`
2. `POST /api/favorites/companies`

---

## 4. 企业详情页

### 页面目标

1. 展示企业基础信息
2. 展示该企业当前在招职位
3. 支持收藏企业

### 页面字段

1. `company_name`
2. `industry`
3. `company_size`
4. `financing_stage`
5. `official_site_url`
6. `careers_url`
7. 企业职位列表

### 接口依赖

1. `GET /api/companies/{company_id}/jobs`
2. `POST /api/favorites/companies`

---

## 5. 收藏页

### 页面目标

集中管理用户的收藏和订阅内容。

### 子模块

1. 收藏企业
2. 收藏职位
3. 收藏搜索条件

### 字段

#### 收藏企业
1. `company_id`
2. `company_name`
3. `latest_job_count`
4. `careers_url`

#### 收藏搜索条件
1. `keyword`
2. `city_name`
3. `filters`
4. `enabled`

### 接口依赖

1. `GET /api/favorites/companies`
2. `GET /api/saved-searches`
3. `DELETE /api/favorites/companies/{company_id}`

---

## 6. 通知页

### 页面目标

向用户展示：

1. 新职位提醒
2. 收藏企业新增岗位提醒
3. 职位更新提醒
4. 职位下线提醒

### 页面字段

1. `notification_type`
2. `title`
3. `content`
4. `is_read`
5. `created_at`
6. `related_job_id`
7. `related_company_id`

### 接口依赖

1. `GET /api/notifications`
2. `POST /api/notifications/{notification_id}/read`

---

## 7. 我的页面

### 页面目标

1. 用户信息展示
2. 提醒开关设置
3. 订阅管理入口
4. 清除搜索历史

### 字段

1. 用户昵称
2. 手机号或账号
3. 通知开关
4. 收藏数量统计

---

## 三、前端 Model 建议

## 1. JobItemModel

```dart
class JobItemModel {
  final int jobId;
  final String title;
  final String companyName;
  final String cityName;
  final String districtName;
  final String salaryText;
  final String degreeText;
  final String experienceText;
  final String sourceName;
  final String officialApplyUrl;
  final String publishedAt;
}
```

## 2. JobDetailModel

```dart
class JobDetailModel {
  final int jobId;
  final String title;
  final String descriptionText;
  final String sourceUrl;
  final String officialApplyUrl;
  final String status;
  final CompanyModel company;
}
```

## 3. CompanyModel

```dart
class CompanyModel {
  final int companyId;
  final String companyName;
  final String industry;
  final String companySize;
  final String financingStage;
  final String officialSiteUrl;
  final String careersUrl;
}
```

## 4. NotificationModel

```dart
class NotificationModel {
  final int notificationId;
  final String notificationType;
  final String title;
  final String content;
  final bool isRead;
  final String createdAt;
}
```

## 四、页面跳转关系

```text
首页搜索页 -> 职位列表页 -> 职位详情页 -> 官网投递
                         -> 企业详情页
收藏页 -> 企业详情页
通知页 -> 职位详情页 / 企业详情页
```

## 五、MVP 前端开发顺序

1. 首页搜索页
2. 职位列表页
3. 职位详情页
4. 收藏企业
5. 通知页
6. 我的页面

## 六、前端注意事项

1. 职位列表要支持空状态页
2. 官网投递链接要用外部浏览器打开
3. 收藏和通知建议先做本地缓存 + 服务端同步
4. 搜索筛选条件建议封装成统一对象，避免参数混乱
