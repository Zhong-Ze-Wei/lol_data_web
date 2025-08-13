/**
 * 用户标识服务
 * 负责生成、存储和获取唯一用户ID
 * 使用localStorage存储ID，确保同一浏览器的持久性
 */

export const UserIdentifier = {
  /**
   * 获取用户ID
   * 如果localStorage中不存在，则生成一个新的UUID并存储
   * @returns {string} 用户唯一标识ID
   */
  getUserId() {
    let userId = localStorage.getItem('lol_data_user_id');
    if (!userId) {
      userId = this.generateUUID();
      localStorage.setItem('lol_data_user_id', userId);
      console.log('生成新用户ID:', userId);
    }
    return userId;
  },

  /**
   * 生成UUID (v4)
   * 使用标准的UUID v4生成算法
   * @returns {string} 生成的UUID
   */
  generateUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
      const r = Math.random() * 16 | 0;
      const v = c === 'x' ? r : (r & 0x3 | 0x8);
      return v.toString(16);
    });
  }
};

export default UserIdentifier;
