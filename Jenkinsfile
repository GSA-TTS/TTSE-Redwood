// feature branch to stable branch
on_pull_request from: feature_branch, to: dev_branch, {
  mcaas_build_and_push()
  node("agent") {
    container("agent") {
      unstash "workspace"
      mcaas_login_to_registry()
      def images = mcaas_get_images_to_build()
      def img = images[0]
      def fullImage = "${img.registry}/${img.repo}:${img.tag}"
      sh "docker pull ${fullImage}"
      def cid = sh(script: "docker create ${fullImage}", returnStdout: true).trim()
      try {
        sh "docker cp ${cid}:/app/coverage ./coverage"
      } finally {
        sh "docker rm ${cid}"
      }
      stash name: "workspace", useDefaultExcludes: false
      sh "docker rmi ${fullImage} 2>/dev/null || true"
    }
  }
  static_code_analysis()
  mcaas_scan_container_image()
}

on_merge from: feature_branch, to: dev_branch, {
  mcaas_build_and_push()
  node("agent") {
    container("agent") {
      unstash "workspace"
      mcaas_login_to_registry()
      def images = mcaas_get_images_to_build()
      def img = images[0]
      def fullImage = "${img.registry}/${img.repo}:${img.tag}"
      sh "docker pull ${fullImage}"
      def cid = sh(script: "docker create ${fullImage}", returnStdout: true).trim()
      try {
        sh "docker cp ${cid}:/app/coverage ./coverage"
      } finally {
        sh "docker rm ${cid}"
      }
      stash name: "workspace", useDefaultExcludes: false
      sh "docker rmi ${fullImage} 2>/dev/null || true"
    }
  }
  static_code_analysis()
  mcaas_scan_container_image()
  mcaas_retag(env.GIT_SHA, "dev-" + env.GIT_SHA + "-" + currentBuild.startTimeInMillis)
}

on_pull_request from: feature_branch, to: staging_branch, {
  mcaas_build_and_push()
  node("agent") {
    container("agent") {
      unstash "workspace"
      mcaas_login_to_registry()
      def images = mcaas_get_images_to_build()
      def img = images[0]
      def fullImage = "${img.registry}/${img.repo}:${img.tag}"
      sh "docker pull ${fullImage}"
      def cid = sh(script: "docker create ${fullImage}", returnStdout: true).trim()
      try {
        sh "docker cp ${cid}:/app/coverage ./coverage"
      } finally {
        sh "docker rm ${cid}"
      }
      stash name: "workspace", useDefaultExcludes: false
      sh "docker rmi ${fullImage} 2>/dev/null || true"
    }
  }
  static_code_analysis()
  mcaas_scan_container_image()
}

on_merge from: feature_branch, to: staging_branch, {
  mcaas_build_and_push()
  node("agent") {
    container("agent") {
      unstash "workspace"
      mcaas_login_to_registry()
      def images = mcaas_get_images_to_build()
      def img = images[0]
      def fullImage = "${img.registry}/${img.repo}:${img.tag}"
      sh "docker pull ${fullImage}"
      def cid = sh(script: "docker create ${fullImage}", returnStdout: true).trim()
      try {
        sh "docker cp ${cid}:/app/coverage ./coverage"
      } finally {
        sh "docker rm ${cid}"
      }
      stash name: "workspace", useDefaultExcludes: false
      sh "docker rmi ${fullImage} 2>/dev/null || true"
    }
  }
  static_code_analysis()
  mcaas_scan_container_image()
  mcaas_retag(env.GIT_SHA, "staging-" + env.GIT_SHA + "-" + currentBuild.startTimeInMillis)
}

on_pull_request from: feature_branch, to: prod_branch, {
  mcaas_build_and_push()
  node("agent") {
    container("agent") {
      unstash "workspace"
      mcaas_login_to_registry()
      def images = mcaas_get_images_to_build()
      def img = images[0]
      def fullImage = "${img.registry}/${img.repo}:${img.tag}"
      sh "docker pull ${fullImage}"
      def cid = sh(script: "docker create ${fullImage}", returnStdout: true).trim()
      try {
        sh "docker cp ${cid}:/app/coverage ./coverage"
      } finally {
        sh "docker rm ${cid}"
      }
      stash name: "workspace", useDefaultExcludes: false
      sh "docker rmi ${fullImage} 2>/dev/null || true"
    }
  }
  static_code_analysis()
  mcaas_scan_container_image()
}

on_merge from: feature_branch, to: prod_branch, {
  mcaas_build_and_push()
  node("agent") {
    container("agent") {
      unstash "workspace"
      mcaas_login_to_registry()
      def images = mcaas_get_images_to_build()
      def img = images[0]
      def fullImage = "${img.registry}/${img.repo}:${img.tag}"
      sh "docker pull ${fullImage}"
      def cid = sh(script: "docker create ${fullImage}", returnStdout: true).trim()
      try {
        sh "docker cp ${cid}:/app/coverage ./coverage"
      } finally {
        sh "docker rm ${cid}"
      }
      stash name: "workspace", useDefaultExcludes: false
      sh "docker rmi ${fullImage} 2>/dev/null || true"
    }
  }
  static_code_analysis()
  mcaas_scan_container_image()
  mcaas_retag(env.GIT_SHA, "prod-" + env.GIT_SHA + "-" + currentBuild.startTimeInMillis)
}


// stable branch to stable branch
on_pull_request from: dev_branch, to: staging_branch, {
  mcaas_build_and_push()
  node("agent") {
    container("agent") {
      unstash "workspace"
      mcaas_login_to_registry()
      def images = mcaas_get_images_to_build()
      def img = images[0]
      def fullImage = "${img.registry}/${img.repo}:${img.tag}"
      sh "docker pull ${fullImage}"
      def cid = sh(script: "docker create ${fullImage}", returnStdout: true).trim()
      try {
        sh "docker cp ${cid}:/app/coverage ./coverage"
      } finally {
        sh "docker rm ${cid}"
      }
      stash name: "workspace", useDefaultExcludes: false
      sh "docker rmi ${fullImage} 2>/dev/null || true"
    }
  }
  static_code_analysis()
  mcaas_scan_container_image()
}

on_merge from: dev_branch, to: staging_branch, {
  mcaas_build_and_push()
  node("agent") {
    container("agent") {
      unstash "workspace"
      mcaas_login_to_registry()
      def images = mcaas_get_images_to_build()
      def img = images[0]
      def fullImage = "${img.registry}/${img.repo}:${img.tag}"
      sh "docker pull ${fullImage}"
      def cid = sh(script: "docker create ${fullImage}", returnStdout: true).trim()
      try {
        sh "docker cp ${cid}:/app/coverage ./coverage"
      } finally {
        sh "docker rm ${cid}"
      }
      stash name: "workspace", useDefaultExcludes: false
      sh "docker rmi ${fullImage} 2>/dev/null || true"
    }
  }
  static_code_analysis()
  mcaas_scan_container_image()
  mcaas_retag(env.GIT_SHA, "staging-" + env.GIT_SHA + "-" + currentBuild.startTimeInMillis)
}

on_pull_request from: staging_branch, to: prod_branch, {
  mcaas_build_and_push()
  node("agent") {
    container("agent") {
      unstash "workspace"
      mcaas_login_to_registry()
      def images = mcaas_get_images_to_build()
      def img = images[0]
      def fullImage = "${img.registry}/${img.repo}:${img.tag}"
      sh "docker pull ${fullImage}"
      def cid = sh(script: "docker create ${fullImage}", returnStdout: true).trim()
      try {
        sh "docker cp ${cid}:/app/coverage ./coverage"
      } finally {
        sh "docker rm ${cid}"
      }
      stash name: "workspace", useDefaultExcludes: false
      sh "docker rmi ${fullImage} 2>/dev/null || true"
    }
  }
  static_code_analysis()
  mcaas_scan_container_image()
}

on_merge from: staging_branch, to: prod_branch, {
  mcaas_build_and_push()
  node("agent") {
    container("agent") {
      unstash "workspace"
      mcaas_login_to_registry()
      def images = mcaas_get_images_to_build()
      def img = images[0]
      def fullImage = "${img.registry}/${img.repo}:${img.tag}"
      sh "docker pull ${fullImage}"
      def cid = sh(script: "docker create ${fullImage}", returnStdout: true).trim()
      try {
        sh "docker cp ${cid}:/app/coverage ./coverage"
      } finally {
        sh "docker rm ${cid}"
      }
      stash name: "workspace", useDefaultExcludes: false
      sh "docker rmi ${fullImage} 2>/dev/null || true"
    }
  }
  static_code_analysis()
  mcaas_scan_container_image()
  mcaas_retag(env.GIT_SHA, "prod-" + env.GIT_SHA + "-" + currentBuild.startTimeInMillis)
}
